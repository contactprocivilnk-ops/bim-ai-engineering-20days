import argparse
import ast
import json
import logging
import os
import random
import re
import shutil
import sys
import time
import traceback
from pathlib import Path

import httpx
from dotenv import load_dotenv
from google import genai
from google.genai import errors as genai_errors
from google.genai import types
from pydantic import BaseModel, Field, ValidationError, field_validator

from db_manager_v2 import (get_tool_records, init_database, log_agent_run, mark_failed,
                           register_tool, update_tool_status)

logging.basicConfig(level=logging.INFO, format="%(message)s")
log = logging.getLogger("stateful_generator")

load_dotenv()
MODEL_ID = os.getenv("GEMINI_MODEL_ID", "gemini-3.8-flash")
# comma-separated models tried in order when a model's quota is exhausted (quotas are per model)
FALLBACK_MODELS = [m.strip() for m in os.getenv("GEMINI_FALLBACK_MODELS", "").split(",") if m.strip()]
REQUEST_TIMEOUT_MS = 120_000

BASE_DIR = Path(__file__).resolve().parent
DEPLOY_BASE_DIR = BASE_DIR / "output_extensions" / "BIM_AI_Stateful.extension" / "StatefulAudit.tab"

_client = None


def get_client():
    """Created lazily so importing this module never raises or needs a key."""
    global _client
    if _client is None:
        key = os.getenv("GEMINI_API_KEY")
        if not key:
            raise RuntimeError("GEMINI_API_KEY not found in environment / .env")
        _client = genai.Client(api_key=key,
                               http_options=types.HttpOptions(timeout=REQUEST_TIMEOUT_MS))
    return _client


# ---------------------------------------------------------------------------
# 1. LLM resilience
# ---------------------------------------------------------------------------
class LLMOutputError(Exception):
    """Model answered but the answer is unusable (empty, truncated, not JSON)."""


RETRYABLE_HTTP = {408, 429, 500, 502, 503, 504}
TRANSPORT_ERRORS = (httpx.TransportError, TimeoutError, ConnectionError)


def _retry_after(exc):
    try:
        value = exc.response.headers.get("retry-after")
        return float(value) if value else None
    except Exception:
        return None


class QuotaExhausted(Exception):
    """429 that will not clear within a normal backoff (e.g. free-tier daily quota)."""


_RETRY_DELAY_RE = re.compile(r"retryDelay'?\"?:\s*'?\"?(\d+(?:\.\d+)?)s")
LONG_WAIT_S = 120.0


def _quota_wait_seconds(exc):
    """Seconds the server asks us to wait if that is long / a per-day quota, else None."""
    text = str(exc)
    m = _RETRY_DELAY_RE.search(text)
    wait = float(m.group(1)) if m else None
    if "PerDay" in text or (wait is not None and wait > LONG_WAIT_S):
        return wait if wait is not None else 86400.0
    return None


def _call_with_retry(model, prompt, config, max_retries, base_delay, max_delay):
    for attempt in range(1, max_retries + 1):
        retry_after = None
        try:
            return get_client().models.generate_content(
                model=model, contents=prompt, config=config)
        except genai_errors.APIError as exc:
            code = getattr(exc, "code", None)
            if code == 429:
                long_wait = _quota_wait_seconds(exc)
                if long_wait is not None:          # retrying now is pointless - fail fast
                    raise QuotaExhausted(
                        "{}: quota exhausted, server asks for {:.1f} h. {}".format(
                            model, long_wait / 3600.0, str(exc)[:200])) from exc
            if code not in RETRYABLE_HTTP or attempt == max_retries:
                raise
            retry_after = _retry_after(exc)
            reason = "HTTP {}".format(code)
        except TRANSPORT_ERRORS as exc:
            if attempt == max_retries:
                raise
            reason = type(exc).__name__            # e.g. WinError 10053 -> httpx.ReadError
        ceiling = min(max_delay, base_delay * 2 ** (attempt - 1))
        wait = ceiling / 2 + random.uniform(0, ceiling / 2)          # "equal jitter"
        if retry_after:
            wait = max(wait, min(retry_after, max_delay))
        log.warning("  [%s] %s retry %d/%d in %.1fs", model, reason, attempt, max_retries - 1, wait)
        time.sleep(wait)


def generate_with_retry(prompt, config, max_retries=5, base_delay=2.0, max_delay=60.0):
    """Backoff + jitter on 408/429(per-minute)/5xx and transport errors. A daily/long
    quota 429 skips to the next model in GEMINI_FALLBACK_MODELS, else raises QuotaExhausted."""
    last = None
    for model in [MODEL_ID] + FALLBACK_MODELS:
        try:
            return _call_with_retry(model, prompt, config, max_retries, base_delay, max_delay)
        except QuotaExhausted as exc:
            last = exc
            log.warning("  %s", exc)
    raise last


def response_text(res) -> str:
    """Text of a response, or LLMOutputError if empty / blocked / truncated."""
    text = getattr(res, "text", None)
    if not text or not text.strip():
        raise LLMOutputError("empty response (blocked or no candidates)")
    try:
        reason = getattr(res.candidates[0].finish_reason, "name", str(res.candidates[0].finish_reason))
    except Exception:
        reason = "STOP"
    if "MAX_TOKENS" in reason:
        raise LLMOutputError("response truncated (MAX_TOKENS) - code would be incomplete")
    return text


_FENCE_RE = re.compile(r"```[ \t]*([A-Za-z0-9_+-]*)[ \t]*\r?\n(.*?)```", re.DOTALL)


def extract_json(text: str):
    """First JSON object/array in `text`; tolerates ```json fences and prose."""
    s = (text or "").strip()
    m = _FENCE_RE.search(s)
    if m:
        s = m.group(2).strip()
    decoder = json.JSONDecoder()
    for i, ch in enumerate(s):
        if ch in "{[":
            try:
                return decoder.raw_decode(s[i:])[0]
            except json.JSONDecodeError:
                continue
    raise LLMOutputError("no JSON found in model output")


def extract_code(text: str) -> str:
    """Longest fenced block (any of ```python / ```py / ```), else the raw text."""
    s = (text or "").strip()
    blocks = [m.group(2) for m in _FENCE_RE.finditer(s)]
    if blocks:
        return max(blocks, key=len).strip()
    return s.strip("`").strip()


# ---------------------------------------------------------------------------
# 2. Schema (names end up in file paths - validate, do not trust)
# ---------------------------------------------------------------------------
_SEGMENT_RE = re.compile(r"^[A-Za-z][A-Za-z0-9_ -]{1,63}$")
_RESERVED = {"con", "prn", "aux", "nul", "com1", "lpt1"}


def _safe_segment(value: str) -> str:
    v = value.strip()
    if not _SEGMENT_RE.match(v) or v.lower() in _RESERVED or v.endswith((".", " ")):
        raise ValueError("unsafe folder name: {!r}".format(value))
    return v


class ToolSpec(BaseModel):
    tool_name: str = Field(description="PascalCase name, e.g., PurgeEmptyDraftingViews")
    panel_name: str = Field(description="pyRevit ribbon panel name, e.g., ViewsAudit")
    description: str = Field(description="Summary of tool functionality")
    required_classes: list[str] = Field(description="Key Revit API classes")
    edge_cases: list[str] = Field(description="Safety checks to handle")

    @field_validator("tool_name", "panel_name")
    @classmethod
    def _folder_safe(cls, v):
        return _safe_segment(v)


def generate_spec(user_prompt: str, attempts: int = 3) -> ToolSpec:
    config = types.GenerateContentConfig(
        response_mime_type="application/json", response_schema=ToolSpec, temperature=0.2)
    prompt = "Design a strict pyRevit pushbutton specification for:\n{!r}".format(user_prompt)
    last = None
    for n in range(1, attempts + 1):
        t0 = time.monotonic()
        try:
            res = generate_with_retry(prompt, config)
            return ToolSpec.model_validate(extract_json(response_text(res)))
        except (ValidationError, LLMOutputError) as exc:
            last = exc
            # trapped + persisted, pipeline continues with another attempt
            log_agent_run(None, "Architect", "FAILED", time.monotonic() - t0,
                          error_msg="attempt {}/{}: {}".format(n, attempts, exc))
            prompt += "\n\nYour previous answer was rejected: {}\nReturn valid JSON only.".format(
                str(exc)[:400])
    raise LLMOutputError("Architect output invalid after {} attempts: {}".format(attempts, last))


# ---------------------------------------------------------------------------
# 3. Static gate for generated pyRevit scripts (before anything is deployed)
# ---------------------------------------------------------------------------
ALLOWED_IMPORT_ROOTS = {
    "clr", "System", "Autodesk", "pyrevit", "rpw", "math", "re", "json", "collections",
    "datetime", "itertools", "traceback", "sys", "os", "time", "__future__"}
BANNED_CALLS = {"eval", "exec", "compile", "__import__", "open"}
BANNED_IMPORTS = {"subprocess", "socket", "requests", "urllib", "urllib2", "shutil", "ctypes",
                  "typing", "dataclasses", "pathlib", "asyncio"}
MODIFY_RE = re.compile(
    r"\.Delete\(|\.Set\(|\.Create\.|NewFamilyInstance|ElementTransformUtils|"
    r"\.Pinned\s*=|\.Name\s*=|\.Move\(|\.Rotate\(|\.Regenerate\(")
UNSAFE_PARAM_RE = re.compile(r"(get_Parameter|LookupParameter)\([^()]*\)\s*\.\s*(As|Set|Has|Is|Storage)")


def validate_generated_script(code: str):
    """(errors, warnings). Errors block deployment."""
    errors, warnings = [], []
    try:
        tree = ast.parse(code)
    except SyntaxError as exc:
        return ["syntax error line {}: {}".format(exc.lineno, exc.msg)], warnings
    for node in ast.walk(tree):
        if isinstance(node, ast.JoinedStr):
            errors.append("f-string at line {} (IronPython 2.7 incompatible)".format(node.lineno))
        elif isinstance(node, (ast.AnnAssign, ast.AsyncFunctionDef, ast.NamedExpr)):
            errors.append("py3-only syntax at line {}".format(node.lineno))
        elif isinstance(node, (ast.FunctionDef,)) and (node.returns or any(
                a.annotation for a in node.args.args)):
            errors.append("type annotations at line {}".format(node.lineno))
        elif isinstance(node, (ast.Import, ast.ImportFrom)):
            mods = [a.name for a in node.names] if isinstance(node, ast.Import) \
                else [node.module or ""]
            for mod in mods:
                root = mod.split(".")[0]
                if root in BANNED_IMPORTS or (root and root not in ALLOWED_IMPORT_ROOTS):
                    errors.append("import not allowed/bundled: {} (line {})".format(mod, node.lineno))
        elif isinstance(node, ast.Call) and isinstance(node.func, ast.Name) \
                and node.func.id in BANNED_CALLS:
            errors.append("banned call {}() at line {}".format(node.func.id, node.lineno))
    if UNSAFE_PARAM_RE.search(code):
        errors.append("parameter used without None-check (get_Parameter/LookupParameter(...).X)")
    modifies = bool(MODIFY_RE.search(code))
    has_txn = bool(re.search(r"\b(Transaction|TransactionGroup)\s*\(", code))
    if modifies and not has_txn:
        errors.append("model-modifying call without Transaction")
    if has_txn and not modifies:
        warnings.append("Transaction present but no modifying call detected (read-only tool?)")
    if "FilteredElementCollector" in code and not re.search(r"\bif\b.*\bnot\b|\bif\b.*\bis None|len\(", code):
        warnings.append("collector results never checked for empty / None")
    return errors, warnings


def pick_valid_code(candidates):
    """First candidate (QA, then draft) that passes the gate."""
    problems = {}
    for label, code in candidates:
        if not isinstance(code, str) or not code.strip():
            problems[label] = ["empty / non-string"]
            continue
        errors, warnings = validate_generated_script(code)
        if not errors:
            return label, code, warnings
        problems[label] = errors
    raise LLMOutputError("generated script failed the static gate: {}".format(problems))


# ---------------------------------------------------------------------------
# 4. Deployment
# ---------------------------------------------------------------------------
CODER_RULES = """
Hard requirements:
- Must run on IronPython 2.7 AND CPython 3: NO f-strings, NO type hints, NO typing imports,
  NO pathlib, NO external libraries. Only clr, System, Autodesk.Revit.*, pyrevit, math, re, json, collections.
- Read-only work runs OUTSIDE any transaction. ALL model modifications go in ONE
  `with revit.Transaction("<tool name>"):` block.
- Read parameters only via element.get_Parameter(BuiltInParameter.X) and test `is not None`
  and `.HasValue` before .AsX().
- Guard every collector result (empty), unplaced rooms (Area == 0 / Location None), invalid
  view types, pinned elements (skip) and grouped elements (skip + warn).
- Report with pyrevit script.get_output(); linkify element ids.
Return only the code in a single ```python block.
"""


def _write_text_atomic(path: Path, text: str) -> None:
    tmp = path.with_name(path.name + ".tmp")
    with open(tmp, "w", encoding="utf-8", newline="\n") as f:
        f.write(text)
    os.replace(tmp, path)


def deploy(spec: ToolSpec, code: str) -> Path:
    base = DEPLOY_BASE_DIR.resolve()
    folder = (base / "{}.panel".format(spec.panel_name) / "{}.pushbutton".format(spec.tool_name)).resolve()
    if base not in folder.parents:
        raise RuntimeError("refusing to write outside the extension: {}".format(folder))
    folder.mkdir(parents=True, exist_ok=True)
    if not code.lstrip().startswith(("# -*- coding", "#!")):
        code = "# -*- coding: utf-8 -*-\n" + code
    script = folder / "script.py"
    if script.exists():
        shutil.copy2(script, folder / "script.py.bak")
    _write_text_atomic(script, code.rstrip() + "\n")
    _write_text_atomic(folder / "bundle.yaml", "title: {}\nauthor: Stateful AI Tool Synthesizer\n"
                       .format(spec.tool_name))
    return folder


# ---------------------------------------------------------------------------
# 5. Pipeline
# ---------------------------------------------------------------------------
def run_stateful_pipeline(user_prompt: str):
    init_database()
    log.info("=" * 65)
    log.info("Stateful AI Tool Synthesizer | model %s\nPrompt: %s", MODEL_ID, user_prompt)
    log.info("=" * 65)

    tool_id, stage, t_stage = None, "Architect", time.monotonic()
    try:
        log.info("[1/4] Architect: specification...")
        spec = generate_spec(user_prompt)
        tool_id = register_tool(spec.tool_name, spec.panel_name, spec.description)
        log_agent_run(tool_id, "Architect", "SUCCESS", time.monotonic() - t_stage,
                      payload=spec.model_dump_json())

        stage, t_stage = "Coder", time.monotonic()
        log.info("[2/4] Coder: synthesizing script...")
        res = generate_with_retry(
            "Write a complete pyRevit script.py.\nName: {}\nClasses: {}\nEdge cases: {}\n{}".format(
                spec.tool_name, spec.required_classes, spec.edge_cases, CODER_RULES),
            types.GenerateContentConfig(temperature=0.2, max_output_tokens=16384))
        draft = extract_code(response_text(res))
        update_tool_status(tool_id, "CODED")
        log_agent_run(tool_id, "Coder", "SUCCESS", time.monotonic() - t_stage,
                      payload="lines: {}".format(len(draft.splitlines())))

        stage, t_stage = "QA_Reviewer", time.monotonic()
        log.info("[3/4] QA Reviewer: auditing...")
        res = generate_with_retry(
            "Review this pyRevit code for null safety, transactions and IronPython 2.7 "
            "compatibility.\nSpecs: {}\nCode:\n{}\n{}\nReturn a JSON object with key "
            "'final_code' (string) containing the corrected script."
            .format(spec.model_dump_json(), draft, CODER_RULES),
            types.GenerateContentConfig(response_mime_type="application/json",
                                        temperature=0.1, max_output_tokens=16384))
        qa_code = None
        try:
            obj = extract_json(response_text(res))
            qa_code = obj.get("final_code") if isinstance(obj, dict) else None
        except LLMOutputError as exc:
            log.warning("  QA output unusable (%s) - falling back to the draft", exc)
        label, final_code, warnings = pick_valid_code([("qa", qa_code), ("draft", draft)])
        update_tool_status(tool_id, "REVIEWED")
        log_agent_run(tool_id, "QA_Reviewer", "SUCCESS", time.monotonic() - t_stage,
                      payload=json.dumps({"used": label, "warnings": warnings}))

        stage, t_stage = "Deploy", time.monotonic()
        log.info("[4/4] Deploying...")
        folder = deploy(spec, final_code)
        update_tool_status(tool_id, "DEPLOYED", filesystem_path=str(folder))
        log_agent_run(tool_id, "Deploy", "SUCCESS", time.monotonic() - t_stage, payload=str(folder))
        log.info("[SUCCESS] %s (ID %s) -> %s", spec.tool_name, tool_id, folder)
        return folder

    except BaseException as exc:                      # includes KeyboardInterrupt
        tb = traceback.format_exc()
        log.error("[FAILURE] stage %s: %s", stage, exc)
        try:
            mark_failed(tool_id, stage, tb, time.monotonic() - t_stage)
        except Exception:                              # never mask the original error
            log.exception("could not persist the failure to the database")
        raise


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Stateful pyRevit Tool Generator")
    parser.add_argument("--prompt", default="Audit all drafting views with zero elements")
    run_stateful_pipeline(parser.parse_args().prompt)
    for row in get_tool_records():
        print(row)
