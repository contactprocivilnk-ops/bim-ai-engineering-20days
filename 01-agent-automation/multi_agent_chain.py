import os
import json
import time
from dotenv import load_dotenv
from google import genai
from google.genai import types
from pydantic import BaseModel, Field

# 1. Initialize environment & API client
load_dotenv()
api_key = os.getenv("GEMINI_API_KEY")

if not api_key:
    raise ValueError("GEMINI_API_KEY not found in .env file.")

client = genai.Client(api_key=api_key)
MODEL_ID = "gemini-3.8-flash"

# Helper function: Automatic retry on 503 transient server load
def generate_with_retry(prompt: str, config: types.GenerateContentConfig, retries: int = 3, delay: int = 4):
    for attempt in range(1, retries + 1):
        try:
            return client.models.generate_content(
                model=MODEL_ID,
                contents=prompt,
                config=config,
            )
        except Exception as exc:
            if "503" in str(exc) and attempt < retries:
                print(f"  [Server Busy 503] Retrying in {delay}s (Attempt {attempt}/{retries})...")
                time.sleep(delay)
            else:
                raise exc

# 2. Pydantic schema for Agent 1 (Planner Specs)
class ToolArchitectureSpec(BaseModel):
    tool_name: str = Field(description="PascalCase tool name, e.g., UnplacedRoomAuditor")
    panel_name: str = Field(description="pyRevit ribbon panel name, e.g., Rooms")
    required_revit_classes: list[str] = Field(description="Revit API classes required, e.g., FilteredElementCollector, SpatialElement")
    edge_cases: list[str] = Field(description="List of critical edge cases to prevent Revit crashes")
    functional_steps: list[str] = Field(description="Step-by-step logic execution plan")

# 3. Agent 1: The Specs Planner
def run_planner_agent(user_request: str) -> ToolArchitectureSpec:
    print("\n[Stage 1/3] Running Planner Agent (Architect)...")
    prompt = f"""
    You are an expert BIM Software Architect.
    Analyze this request and generate a strict technical specification for a pyRevit pushbutton tool:
    Request: "{user_request}"
    """
    config = types.GenerateContentConfig(
        response_mime_type="application/json",
        response_schema=ToolArchitectureSpec,
        temperature=0.2,
    )
    response = generate_with_retry(prompt, config)
    return ToolArchitectureSpec.model_validate_json(response.text)

# 4. Agent 2: The Code Generator
def run_coder_agent(specs: ToolArchitectureSpec) -> str:
    print("[Stage 2/3] Running Developer Agent (Coder)...")
    prompt = f"""
    You are a Senior pyRevit Python Developer.
    Write a complete, robust script.py file using pyRevit modules (revit, DB, forms) based strictly on these specs:
    Tool Name: {specs.tool_name}
    Revit Classes: {specs.required_revit_classes}
    Edge Cases: {specs.edge_cases}
    Functional Steps: {specs.functional_steps}

    Requirements:
    - Include full imports, docstring, and error handling.
    - Wrap modifications inside revit.Transaction (if modifying) or handle read-only collectors safely.
    - Return ONLY pure Python code. No markdown tags, no backticks.
    """
    config = types.GenerateContentConfig(temperature=0.2)
    response = generate_with_retry(prompt, config)
    raw_code = response.text.strip()
    if raw_code.startswith("```python"):
        raw_code = raw_code[9:]
    if raw_code.startswith("```"):
        raw_code = raw_code[3:]
    if raw_code.endswith("```"):
        raw_code = raw_code[:-3]
    return raw_code.strip()

# 5. Agent 3: The QA Code Reviewer
def run_reviewer_agent(specs: ToolArchitectureSpec, code: str) -> dict:
    print("[Stage 3/3] Running QA Reviewer Agent (Code Reviewer)...")
    prompt = f"""
    You are a Lead QA Engineer specialized in Autodesk Revit API and pyRevit safety.
    Review the following Python code against the specifications:
    
    Specifications:
    {specs.model_dump_json(indent=2)}
    
    Python Code:
    {code}
    
    Output a JSON object with:
    - "approved": boolean (true/false)
    - "review_notes": list of feedback points
    - "final_code": cleaned/refined code ready for production.
    """
    config = types.GenerateContentConfig(
        response_mime_type="application/json",
        temperature=0.1,
    )
    response = generate_with_retry(prompt, config)
    return json.loads(response.text)

# 6. Main Orchestrator
if __name__ == "__main__":
    test_request = "Create a tool to audit all unplaced rooms in the Revit project and report their count."
    print("=" * 65)
    print("Starting Multi-Agent Chain Pipeline")
    print(f"Goal: {test_request}")
    print("=" * 65)

    specs = run_planner_agent(test_request)
    draft_code = run_coder_agent(specs)
    review_result = run_reviewer_agent(specs, draft_code)

    print("\n--- Pipeline Completed Successfully ---")
    print(f"Tool: {specs.tool_name}")
    print(f"Approved: {review_result.get('approved')}")
    print(f"Review Notes: {review_result.get('review_notes')}")
    print("\nFinal Verified Script Preview (First 8 lines):")
    final_lines = review_result.get('final_code', '').splitlines()[:8]
    print("\n".join(final_lines))