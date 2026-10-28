import os
import sys
import ast
import json
import time
import math
import sqlite3
import argparse
from pathlib import Path
from datetime import datetime, timezone
from dotenv import load_dotenv
from google import genai
from google.genai import types
from pydantic import BaseModel, Field

# Setup Paths
BASE_DIR = Path(__file__).resolve().parent
ROOT_DIR = BASE_DIR.parent
ENV_FILE = ROOT_DIR / ".env"
load_dotenv(ENV_FILE if ENV_FILE.exists() else None)

api_key = os.getenv("GEMINI_API_KEY")
if not api_key:
    raise ValueError("GEMINI_API_KEY not found in environment.")

client = genai.Client(api_key=api_key)
LLM_MODEL = "gemini-3.8-flash"
EMBEDDING_MODEL = "gemini-embedding-001"

DB_PATH = ROOT_DIR / "02-data-engineering" / "bim_tools_vault.db"
VECTOR_INDEX_PATH = ROOT_DIR / "03-revit-rag-system" / "revit_vector_index.json"
PRODUCTION_DIR = BASE_DIR / "output_extensions" / "BIM_AI_Production.extension" / "Production.tab"

def get_current_timestamp() -> str:
    return datetime.now(timezone.utc).isoformat()

def log(msg: str):
    """Prints message immediately with flushed stdout to prevent terminal buffering."""
    print(msg, flush=True)

# --- 1. RAG & Vector Engine ---
def get_embedding(text: str) -> list[float]:
    response = client.models.embed_content(
        model=EMBEDDING_MODEL,
        contents=text,
    )
    if hasattr(response, "embedding") and response.embedding:
        return response.embedding.values
    elif hasattr(response, "embeddings") and response.embeddings:
        return response.embeddings[0].values
    raise ValueError("Failed to retrieve embeddings from response.")

def cosine_similarity(v1: list[float], v2: list[float]) -> float:
    dot = sum(a * b for a, b in zip(v1, v2))
    norm_a = math.sqrt(sum(a * a for a in v1))
    norm_b = math.sqrt(sum(b * b for b in v2))
    return dot / (norm_a * norm_b) if norm_a and norm_b else 0.0

def retrieve_rag_context(query: str, top_k: int = 2) -> tuple[str, list[str]]:
    if not VECTOR_INDEX_PATH.exists():
        return "", []
    with open(VECTOR_INDEX_PATH, "r", encoding="utf-8") as f:
        index_data = json.load(f)
    query_vec = get_embedding(query)
    scored = []
    for item in index_data:
        sim = cosine_similarity(query_vec, item["embedding"])
        scored.append((sim, item))
    scored.sort(key=lambda x: x[0], reverse=True)
    top_matches = scored[:top_k]
    
    context_str = ""
    classes = []
    for score, item in top_matches:
        classes.append(f"{item['class_name']} ({score:.2f})")
        context_str += f"\n--- SPEC CONTEXT: {item['class_name']} ---\n{item['content']}\n"
    return context_str, classes

# --- 2. Database State Management ---
def log_tool_state(tool_name: str, panel: str, desc: str) -> int:
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    cursor.execute("SELECT id FROM tools WHERE name = ?", (tool_name,))
    row = cursor.fetchone()
    now = get_current_timestamp()
    if row:
        tool_id = row[0]
        cursor.execute("UPDATE tools SET status = 'PLANNED', updated_at = ? WHERE id = ?", (now, tool_id))
    else:
        cursor.execute("""
            INSERT INTO tools (name, target_panel, description, status, created_at, updated_at)
            VALUES (?, ?, ?, 'PLANNED', ?, ?)
        """, (tool_name, panel, desc, now, now))
        tool_id = cursor.lastrowid
    conn.commit()
    conn.close()
    return tool_id

def update_status(tool_id: int, status: str, fs_path: str = None):
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    now = get_current_timestamp()
    if fs_path:
        cursor.execute("UPDATE tools SET status = ?, filesystem_path = ?, updated_at = ? WHERE id = ?", (status, fs_path, now, tool_id))
    else:
        cursor.execute("UPDATE tools SET status = ?, updated_at = ? WHERE id = ?", (status, now, tool_id))
    conn.commit()
    conn.close()

def log_agent_run(tool_id: int, role: str, status: str, latency: float, error_msg: str = None):
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    cursor.execute("""
        INSERT INTO generation_runs (tool_id, agent_role, status, duration_seconds, error_message, timestamp)
        VALUES (?, ?, ?, ?, ?, ?)
    """, (tool_id, role, status, latency, error_msg, get_current_timestamp()))
    conn.commit()
    conn.close()

# --- 3. Robust API & Network Retry ---
def generate_with_retry(prompt: str, config: types.GenerateContentConfig, max_retries: int = 6, base_delay: int = 5):
    transient_triggers = ("503", "10054", "readerror", "remoteprotocolerror", "connection", "reset", "timeout", "servererror")
    
    for attempt in range(1, max_retries + 1):
        try:
            return client.models.generate_content(
                model=LLM_MODEL,
                contents=prompt,
                config=config,
            )
        except Exception as exc:
            err_msg = str(exc).lower()
            is_transient = any(trigger in err_msg for trigger in transient_triggers)
            
            if is_transient and attempt < max_retries:
                wait_time = base_delay * attempt
                log(f"  [Transient Issue] Retrying in {wait_time}s ({attempt}/{max_retries})... Reason: {type(exc).__name__}")
                time.sleep(wait_time)
            else:
                log(f"  [CRITICAL ERROR] Failed on attempt {attempt}: {str(exc)}")
                raise exc

class ToolSpec(BaseModel):
    tool_name: str = Field(description="PascalCase name of the pyRevit command")
    panel_name: str = Field(description="Target ribbon panel name")
    description: str = Field(description="Concise description of tool functionality")
    required_classes: list[str] = Field(description="Revit API classes required")

# --- 4. Main Orchestration Pipeline ---
def orchestrate_production_pipeline(user_prompt: str):
    log("\n" + "=" * 80)
    log(" UNIFIED AUTONOMOUS PRODUCTION ORCHESTRATOR")
    log(f" Prompt: '{user_prompt}'")
    log("=" * 80)

    # 1. RAG Retrieval
    log("\n[Stage 1/5] RAG Retrieval: Querying API knowledge base...")
    t0 = time.time()
    rag_context, top_classes = retrieve_rag_context(user_prompt, top_k=2)
    rag_latency = round(time.time() - t0, 2)
    log(f"  Retrieved Documentation: {', '.join(top_classes)} (in {rag_latency}s)")

    # 2. Architect Agent
    log("\n[Stage 2/5] Architect Agent: Designing specification...")
    t0 = time.time()
    spec_prompt = f"""
    You are a Principal Revit API Software Architect.
    Using this technical context:
    {rag_context}
    
    Design a pyRevit tool specification for:
    '{user_prompt}'
    """
    config = types.GenerateContentConfig(
        response_mime_type="application/json",
        response_schema=ToolSpec,
        temperature=0.1
    )
    res = generate_with_retry(spec_prompt, config)
    spec = ToolSpec.model_validate_json(res.text)
    t_arch = round(time.time() - t0, 2)

    tool_id = log_tool_state(spec.tool_name, spec.panel_name, spec.description)
    log_agent_run(tool_id, "Architect", "SUCCESS", t_arch)
    log(f"  Tool ID #{tool_id}: '{spec.tool_name}' registered on panel '{spec.panel_name}'.")

    # 3. Coder Agent
    log("\n[Stage 3/5] Coder Agent: Synthesizing script...")
    t0 = time.time()
    coder_prompt = f"""
    Synthesize complete, production-grade pyRevit script.py for:
    Name: {spec.tool_name}
    Panel: {spec.panel_name}
    Classes: {spec.required_classes}
    
    RAG SDK CONTEXT:
    {rag_context}
    
    RULES:
    - Enclose document changes in 'with revit.Transaction("Name"):'.
    - Apply null checks and verify doc.IsWorkshared if using worksets.
    - Return pure executable Python code only (no markdown).
    """
    config = types.GenerateContentConfig(temperature=0.1)
    
    try:
        res = generate_with_retry(coder_prompt, config)
        code = res.text.strip()
        if code.startswith("```python"):
            code = code[9:]
        if code.startswith("```"):
            code = code[3:]
        if code.endswith("```"):
            code = code[:-3]
        code = code.strip()
        t_coder = round(time.time() - t0, 2)
        update_status(tool_id, "CODED")
        log_agent_run(tool_id, "Coder", "SUCCESS", t_coder)
        log(f"  Coder Agent completed in {t_coder}s.")
    except Exception as e:
        update_status(tool_id, "FAILED")
        log_agent_run(tool_id, "Coder", "FAILED", round(time.time() - t0, 2), str(e))
        log(f"[FATAL] Coder Agent failed: {e}")
        return

    # 4. AST Integrity & QA Audit
    log("\n[Stage 4/5] Integrity Audit: Compiling Abstract Syntax Tree...")
    try:
        ast.parse(code)
        log("  AST Syntax: PASS [✓]")
    except SyntaxError as e:
        log(f"  AST Syntax: FAIL [✗] (Line {e.lineno}: {e.msg})")
        update_status(tool_id, "FAILED")
        log_agent_run(tool_id, "QA_Audit", "FAILED", 0.0, f"Syntax Error: {e.msg}")
        return

    update_status(tool_id, "REVIEWED")
    log_agent_run(tool_id, "QA_Audit", "SUCCESS", 0.05)

    # 5. Production Deployment
    log("\n[Stage 5/5] Deployment: Writing bundle to pyRevit extension structure...")
    target_bundle = PRODUCTION_DIR / f"{spec.panel_name}.panel" / f"{spec.tool_name}.pushbutton"
    target_bundle.mkdir(parents=True, exist_ok=True)
    script_file = target_bundle / "script.py"

    with open(script_file, "w", encoding="utf-8") as f:
        f.write(code)

    update_status(tool_id, "DEPLOYED", str(target_bundle))

    log("\n" + "=" * 80)
    log(f" [PIPELINE SUCCESS] Tool '{spec.tool_name}' deployed to production!")
    log(f" Path: {script_file}")
    log(f" Database Status: DEPLOYED (Record ID: {tool_id})")
    log("=" * 80 + "\n")

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Unified Autonomous Orchestrator")
    parser.add_argument("--prompt", type=str, default="Audit user-created worksets in the model", help="User requirement")
    args = parser.parse_args()

    orchestrate_production_pipeline(args.prompt)