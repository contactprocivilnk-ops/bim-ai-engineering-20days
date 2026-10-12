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

# 1. Environment & Paths Configuration
load_dotenv()
api_key = os.getenv("GEMINI_API_KEY")

if not api_key:
    raise ValueError("GEMINI_API_KEY not found in .env file.")

client = genai.Client(api_key=api_key)
MODEL_ID = "gemini-3.8-flash"

BASE_DIR = Path(__file__).resolve().parent
DEFAULT_EXT_DIR = BASE_DIR / "output_extensions" / "BIM_AI_Automation.extension" / "Automation.tab"

# Robust execution helper with Exponential Backoff
def generate_with_retry(prompt: str, config: types.GenerateContentConfig, max_retries: int = 5, base_delay: int = 3):
    for attempt in range(1, max_retries + 1):
        try:
            return client.models.generate_content(
                model=MODEL_ID,
                contents=prompt,
                config=config,
            )
        except Exception as exc:
            if "503" in str(exc) and attempt < max_retries:
                wait_time = base_delay * (2 ** (attempt - 1))
                print(f"  [Server Busy 503] Retrying in {wait_time}s (Attempt {attempt}/{max_retries})...")
                time.sleep(wait_time)
            else:
                raise exc

# 2. Schemas
class ToolSpec(BaseModel):
    tool_name: str = Field(description="Strict PascalCase name for button directory, e.g., FilterUnusedViews")
    panel_name: str = Field(description="pyRevit ribbon panel name, e.g., Views")
    description: str = Field(description="Concise description of the tool")
    required_classes: list[str] = Field(description="Key Revit API classes required")
    edge_cases: list[str] = Field(description="Critical safety checks to prevent crashes")

# 3. Agent Functions
def plan_tool(intent: str) -> ToolSpec:
    print("\n[Step 1/4] Architect Agent: Designing specifications...")
    prompt = f"Design a strict pyRevit pushbutton tool specification for this user intent:\n'{intent}'"
    config = types.GenerateContentConfig(
        response_mime_type="application/json",
        response_schema=ToolSpec,
        temperature=0.2,
    )
    res = generate_with_retry(prompt, config)
    return ToolSpec.model_validate_json(res.text)

def code_tool(spec: ToolSpec) -> str:
    print("[Step 2/4] Developer Agent: Synthesizing pyRevit Python code...")
    prompt = f"""
    Write a complete, high-quality script.py for pyRevit:
    Tool Name: {spec.tool_name}
    Revit Classes: {spec.required_classes}
    Edge Cases: {spec.edge_cases}
    
    Rules:
    - Target Python 2.7 / 3 compatible syntax as required by IronPython/pyRevit.
    - Wrap modifications in revit.Transaction.
    - Provide clear user notifications via pyrevit.forms.
    - Return ONLY executable Python code. No backticks, no explanations.
    """
    config = types.GenerateContentConfig(temperature=0.2)
    res = generate_with_retry(prompt, config)
    raw = res.text.strip()
    if raw.startswith("```python"):
        raw = raw[9:]
    if raw.startswith("```"):
        raw = raw[3:]
    if raw.endswith("```"):
        raw = raw[:-3]
    return raw.strip()

def review_tool(spec: ToolSpec, code: str) -> str:
    print("[Step 3/4] QA Agent: Validating Revit API transactions & edge cases...")
    prompt = f"""
    Review this pyRevit code against specifications:
    Specs: {spec.model_dump_json()}
    Code:
    {code}
    
    Refine if necessary to ensure zero runtime crashes and strict transaction safety.
    Return a JSON object with:
    - "final_code": string containing the production-ready python script.
    """
    config = types.GenerateContentConfig(
        response_mime_type="application/json",
        temperature=0.1,
    )
    res = generate_with_retry(prompt, config)
    data = json.loads(res.text)
    return data.get("final_code", code)

def scaffold_tool(spec: ToolSpec, final_code: str, output_base: Path):
    print("[Step 4/4] Filesystem Agent: Deploying pyRevit structure...")
    panel_dir = output_base / f"{spec.panel_name}.panel"
    button_dir = panel_dir / f"{spec.tool_name}.pushbutton"
    button_dir.mkdir(parents=True, exist_ok=True)
    
    script_file = button_dir / "script.py"
    with open(script_file, "w", encoding="utf-8") as f:
        f.write(final_code)
    
    meta_file = button_dir / "metadata.json"
    with open(meta_file, "w", encoding="utf-8") as f:
        f.write(spec.model_dump_json(indent=2))

    return button_dir, script_file

# 4. CLI Entry Point
def main():
    parser = argparse.ArgumentParser(description="End-to-End AI Engineering CLI for pyRevit Tools.")
    parser.add_argument("--prompt", type=str, help="Describe the Revit automation tool you need.")
    args = parser.parse_args()

    user_prompt = args.prompt
    if not user_prompt:
        print("\n=== BIM AI Engineering: Automated pyRevit Tool Synthesizer ===")
        user_prompt = input("Enter tool prompt: ").strip()
        if not user_prompt:
            sys.exit(1)

    start_time = time.time()
    
    # Run the full pipeline with small breathers to avoid server rate spikes
    spec = plan_tool(user_prompt)
    time.sleep(2)
    
    draft_code = code_tool(spec)
    time.sleep(2)
    
    final_code = review_tool(spec, draft_code)
    btn_dir, script_path = scaffold_tool(spec, final_code, DEFAULT_EXT_DIR)
    
    elapsed = round(time.time() - start_time, 2)
    
    print("\n" + "=" * 65)
    print(f" PIPELINE COMPLETE in {elapsed}s")
    print(f" Tool Synthesized : {spec.tool_name}")
    print(f" Panel Placement  : {spec.panel_name}.panel")
    print(f" Target Path      : {btn_dir}")
    print(f" Script Deployed  : {script_path}")
    print("=" * 65 + "\n")

if __name__ == "__main__":
    main()