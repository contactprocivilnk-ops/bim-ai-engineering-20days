import os
import sys
import json
import time
import argparse
from pathlib import Path
from dotenv import load_dotenv
from google import genai
from google.genai import types
from pydantic import BaseModel, Field

# 1. Import DB Manager functions from current directory
from db_manager import init_database, register_tool, update_tool_status, log_agent_run, get_tool_records

# 2. Setup paths and SDK client
load_dotenv()
api_key = os.getenv("GEMINI_API_KEY")

if not api_key:
    raise ValueError("GEMINI_API_KEY not found in .env file.")

client = genai.Client(api_key=api_key)
MODEL_ID = "gemini-3.8-flash"

BASE_DIR = Path(__file__).resolve().parent
DEPLOY_BASE_DIR = BASE_DIR / "output_extensions" / "BIM_AI_Stateful.extension" / "StatefulAudit.tab"

def generate_with_retry(prompt: str, config: types.GenerateContentConfig, max_retries: int = 6, base_delay: int = 5):
    """Executes prompt on gemini-3.8-flash with incremental backoff on transient 503 server load."""
    for attempt in range(1, max_retries + 1):
        try:
            return client.models.generate_content(
                model=MODEL_ID,
                contents=prompt,
                config=config,
            )
        except Exception as exc:
            err_str = str(exc)
            if "503" in err_str and attempt < max_retries:
                wait_time = base_delay * attempt
                print(f"  [Server Busy 503] Google servers under peak load. Retrying in {wait_time}s (Attempt {attempt}/{max_retries})...")
                time.sleep(wait_time)
            else:
                raise exc

# 3. Pydantic Schema
class ToolSpec(BaseModel):
    tool_name: str = Field(description="PascalCase name, e.g., PurgeEmptyDraftingViews")
    panel_name: str = Field(description="pyRevit ribbon panel name, e.g., ViewsAudit")
    description: str = Field(description="Summary of tool functionality")
    required_classes: list[str] = Field(description="Key Revit API classes")
    edge_cases: list[str] = Field(description="Safety checks to handle")

# 4. Agent Pipeline with Integrated DB Logging
def run_stateful_pipeline(user_prompt: str):
    init_database()
    print("=" * 65)
    print("Starting Stateful AI Tool Synthesizer")
    print(f"Model  : {MODEL_ID}")
    print(f"Prompt : {user_prompt}")
    print("=" * 65)

    tool_id = None
    try:
        # Step 1: Architect Agent
        t0 = time.time()
        print("\n[Stage 1/4] Architect Agent: Creating specifications...")
        prompt = f"Design a strict pyRevit pushbutton specification for:\n'{user_prompt}'"
        config = types.GenerateContentConfig(
            response_mime_type="application/json",
            response_schema=ToolSpec,
            temperature=0.2,
        )
        res = generate_with_retry(prompt, config)
        spec = ToolSpec.model_validate_json(res.text)
        t_architect = round(time.time() - t0, 2)

        # Register in Database
        tool_id = register_tool(spec.tool_name, spec.panel_name, spec.description)
        log_agent_run(tool_id, "Architect", "SUCCESS", t_architect, payload=spec.model_dump_json())
        time.sleep(2)

        # Step 2: Coder Agent
        t0 = time.time()
        print("[Stage 2/4] Coder Agent: Synthesizing script...")
        prompt = f"""
        Write a complete pyRevit script.py based on:
        Name: {spec.tool_name}
        Classes: {spec.required_classes}
        Edge Cases: {spec.edge_cases}
        Requirements: Wrap modifications in revit.Transaction, return pure python code only.
        """
        config = types.GenerateContentConfig(temperature=0.2)
        res = generate_with_retry(prompt, config)
        raw_code = res.text.strip()
        if raw_code.startswith("```python"):
            raw_code = raw_code[9:]
        if raw_code.startswith("```"):
            raw_code = raw_code[3:]
        if raw_code.endswith("```"):
            raw_code = raw_code[:-3]
        draft_code = raw_code.strip()
        t_coder = round(time.time() - t0, 2)

        update_tool_status(tool_id, "CODED")
        log_agent_run(tool_id, "Coder", "SUCCESS", t_coder, payload=f"Lines of code: {len(draft_code.splitlines())}")
        time.sleep(2)

        # Step 3: QA Reviewer Agent
        t0 = time.time()
        print("[Stage 3/4] QA Reviewer Agent: Auditing API transactions...")
        prompt = f"""
        Review this pyRevit code for null safety and transactions:
        Specs: {spec.model_dump_json()}
        Code:
        {draft_code}
        Return JSON object with key 'final_code' containing safe script.
        """
        config = types.GenerateContentConfig(
            response_mime_type="application/json",
            temperature=0.1,
        )
        res = generate_with_retry(prompt, config)
        final_code = json.loads(res.text).get("final_code", draft_code)
        t_qa = round(time.time() - t0, 2)

        update_tool_status(tool_id, "REVIEWED")
        log_agent_run(tool_id, "QA_Reviewer", "SUCCESS", t_qa)

        # Step 4: Filesystem Scaffold & Deployment
        print("[Stage 4/4] Deploying to pyRevit structure...")
        button_folder = DEPLOY_BASE_DIR / f"{spec.panel_name}.panel" / f"{spec.tool_name}.pushbutton"
        button_folder.mkdir(parents=True, exist_ok=True)
        script_file = button_folder / "script.py"

        with open(script_file, "w", encoding="utf-8") as f:
            f.write(final_code)

        # Update final deployment status in DB
        update_tool_status(tool_id, "DEPLOYED", filesystem_path=str(button_folder))

        print("\n" + "=" * 65)
        print(f"[SUCCESS] Tool '{spec.tool_name}' (ID: {tool_id}) deployed and persisted to DB.")
        print(f"Location: {button_folder}")
        print("=" * 65)

    except Exception as exc:
        print(f"\n[FAILURE] Pipeline failed: {exc}")
        if tool_id:
            update_tool_status(tool_id, "FAILED")
            log_agent_run(tool_id, "Pipeline", "FAILED", 0.0, error_msg=str(exc))
        raise exc

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Stateful pyRevit Tool Generator")
    parser.add_argument("--prompt", type=str, default="Audit all drafting views with zero elements", help="Tool requirement prompt")
    args = parser.parse_args()

    run_stateful_pipeline(args.prompt)