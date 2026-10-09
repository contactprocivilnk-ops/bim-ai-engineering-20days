import os
import json
from dotenv import load_dotenv
from google import genai
from google.genai import types
from pydantic import BaseModel, Field

# Load API key securely
load_dotenv()
api_key = os.getenv("GEMINI_API_KEY")

if not api_key:
    raise ValueError("GEMINI_API_KEY not found in .env file.")

client = genai.Client(api_key=api_key)

# 1. Define the strict Data Schema using Pydantic
class RevitToolSpec(BaseModel):
    tool_name: str = Field(description="Name of the tool, e.g., ProjectInfoFiller")
    target_panel: str = Field(description="Panel name in pyRevit, e.g., Manage or Setup")
    description: str = Field(description="Brief explanation of the tool functionality")
    edge_cases_handled: list[str] = Field(description="List of edge cases accounted for (e.g. pinned elements, null values)")
    python_script: str = Field(description="Complete, valid python script code for pyRevit (script.py)")

# 2. Prompt specifying the tool requirement
prompt = """
Generate a pyRevit pushbutton tool specification for: 'Project Info Filler'.
It must read project information (Client Name, Project Date) and populate Revit Project Information.
Ensure the code handles pinned parameters and missing inputs safely.
"""

# 3. Request structured JSON output enforced by the schema
response = client.models.generate_content(
    model="gemini-3.8-flash",
    contents=prompt,
    config=types.GenerateContentConfig(
        response_mime_type="application/json",
        response_schema=RevitToolSpec,
        temperature=0.2,  # Low temperature for deterministic output
    ),
)

# 4. Parse and display structured output
parsed_data = json.loads(response.text)

print("\n--- Structured Output Received ---")
print(f"Tool Name: {parsed_data['tool_name']}")
print(f"Target Panel: {parsed_data['target_panel']}")
print(f"Edge Cases: {parsed_data['edge_cases_handled']}")
print("\n--- Python Script Preview (First 5 lines) ---")
print("\n".join(parsed_data['python_script'].splitlines()[:5]))

# Save structured specification to a JSON file
with open("01-agent-automation/tool_spec.json", "w", encoding="utf-8") as f:
    json.dump(parsed_data, f, indent=4, ensure_ascii=False)

print("\n--- Saved successfully to 01-agent-automation/tool_spec.json ---")