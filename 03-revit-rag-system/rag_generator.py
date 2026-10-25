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

# Import search from Day 12
from vector_store import search_knowledge_base

load_dotenv()
api_key = os.getenv("GEMINI_API_KEY")

if not api_key:
    raise ValueError("GEMINI_API_KEY not found in .env file.")

client = genai.Client(api_key=api_key)
MODEL_ID = "gemini-3.8-flash"

BASE_DIR = Path(__file__).resolve().parent
DEPLOY_BASE_DIR = BASE_DIR / "output_extensions" / "BIM_AI_RAG.extension" / "RAGTools.tab"

def generate_with_retry(prompt: str, config: types.GenerateContentConfig, max_retries: int = 5, base_delay: int = 4):
    for attempt in range(1, max_retries + 1):
        try:
            return client.models.generate_content(
                model=MODEL_ID,
                contents=prompt,
                config=config,
            )
        except Exception as exc:
            if "503" in str(exc) and attempt < max_retries:
                wait_time = base_delay * attempt
                print(f"  [Server Busy 503] Retrying in {wait_time}s (Attempt {attempt}/{max_retries})...")
                time.sleep(wait_time)
            else:
                raise exc

class ToolSpec(BaseModel):
    tool_name: str = Field(description="PascalCase name, e.g., AuditEmptyDraftingViews")
    panel_name: str = Field(description="pyRevit ribbon panel name, e.g., Audit")
    description: str = Field(description="Summary of tool purpose")
    required_classes: list[str] = Field(description="Key Revit API classes used")
    grounded_patterns: list[str] = Field(description="Patterns adopted directly from RAG documentation")

def run_rag_pipeline(user_prompt: str):
    print("=" * 75)
    print(" STARTING RAG-AUGMENTED REVIT AGENT PIPELINE")
    print(f" User Prompt: '{user_prompt}'")
    print("=" * 75)

    # Step 1: Retrieval (RAG Query)
    print("\n[Stage 1/4] Knowledge Retrieval: Querying Vector Store...")
    retrieved_docs = search_knowledge_base(user_prompt, top_k=2)
    
    rag_context = ""
    print("  Relevant Documentation Retrieved:")
    for idx, doc in enumerate(retrieved_docs, start=1):
        print(f"    - Doc #{idx}: {doc['class_name']} (Similarity: {doc['similarity']})")
        rag_context += f"\n--- DOCUMENTATION CHUNK: {doc['class_name']} ---\n{doc['content']}\n"

    # Step 2: Architect Agent (Grounded Specification)
    print("\n[Stage 2/4] Architect Agent: Creating grounded specification...")
    architect_prompt = f"""
    You are a Principal Revit API Architect.
    Using the retrieved Revit API technical documentation below, design a robust pushbutton tool spec.
    
    TECHNICAL DOCUMENTATION CONTEXT:
    {rag_context}
    
    USER REQUIREMENT:
    {user_prompt}
    """
    config = types.GenerateContentConfig(
        response_mime_type="application/json",
        response_schema=ToolSpec,
        temperature=0.1,
    )
    res = generate_with_retry(architect_prompt, config)
    spec = ToolSpec.model_validate_json(res.text)
    print(f"  [SPEC CREATED] {spec.tool_name} for panel: {spec.panel_name}")
    print(f"  [GROUNDED CLASSES] {spec.required_classes}")
    time.sleep(2)

    # Step 3: Coder Agent (Grounded Synthesis)
    print("\n[Stage 3/4] Coder Agent: Synthesizing script adhering strictly to RAG constraints...")
    coder_prompt = f"""
    You are an expert pyRevit developer.
    Synthesize a production-ready script.py conforming to the specification and RAG best practices.
    
    STRICT TECHNICAL CONSTRAINTS:
    {rag_context}
    
    TOOL SPECIFICATION:
    {spec.model_dump_json(indent=2)}
    
    CRITICAL RULES:
    1. If modifying elements, enclose in 'with revit.Transaction("Name"):'.
    2. Strictly avoid common pitfalls documented in the context.
    3. Return pure python code only without markdown wrappers.
    """
    config = types.GenerateContentConfig(temperature=0.1)
    res = generate_with_retry(coder_prompt, config)
    raw_code = res.text.strip()
    if raw_code.startswith("```python"):
        raw_code = raw_code[9:]
    if raw_code.startswith("```"):
        raw_code = raw_code[3:]
    if raw_code.endswith("```"):
        raw_code = raw_code[:-3]
    final_code = raw_code.strip()

    # Step 4: Filesystem Deployment
    print("\n[Stage 4/4] Deploying to pyRevit bundle directory...")
    button_folder = DEPLOY_BASE_DIR / f"{spec.panel_name}.panel" / f"{spec.tool_name}.pushbutton"
    button_folder.mkdir(parents=True, exist_ok=True)
    script_file = button_folder / "script.py"

    with open(script_file, "w", encoding="utf-8") as f:
        f.write(final_code)

    print("\n" + "=" * 75)
    print(f"[SUCCESS] RAG-Grounded tool deployed successfully!")
    print(f"Path: {script_file}")
    print("=" * 75 + "\n")

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="RAG-Augmented pyRevit Tool Generator")
    parser.add_argument("--prompt", type=str, default="Delete all unused drafting views that have no elements", help="User requirement")
    args = parser.parse_args()

    run_rag_pipeline(args.prompt)