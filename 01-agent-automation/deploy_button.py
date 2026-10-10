import os
import json
from pathlib import Path

# 1. Define paths
CURRENT_DIR = Path(__file__).resolve().parent
SPEC_FILE = CURRENT_DIR / "test_tool_spec.json"

# Target output directory (local test extension scaffold)
OUTPUT_ROOT = CURRENT_DIR / "output_extensions" / "BIM_AI_Sandbox.extension" / "DevTesting.tab"

def deploy_tool_from_spec():
    if not SPEC_FILE.exists():
        raise FileNotFoundError(f"Specification file not found at: {SPEC_FILE}")

    # 2. Read the structured JSON specification
    with open(SPEC_FILE, "r", encoding="utf-8") as f:
        spec = json.load(f)

    tool_name = spec.get("tool_name", "DefaultTool")
    target_panel = spec.get("target_panel", "General")
    python_script = spec.get("python_script", "")

    # 3. Construct the strict pyRevit hierarchy:
    # Extension -> Tab -> Panel.panel -> ButtonName.pushbutton -> script.py
    panel_folder = OUTPUT_ROOT / f"{target_panel}.panel"
    button_folder = panel_folder / f"{tool_name}.pushbutton"
    script_path = button_folder / "script.py"

    # Create directories recursively
    button_folder.mkdir(parents=True, exist_ok=True)

    # 4. Write script.py
    with open(script_path, "w", encoding="utf-8") as f:
        f.write(python_script)

    print("=" * 60)
    print(f" [SUCCESS] pyRevit PushButton Deployed Successfully!")
    print(f" Tool Name   : {tool_name}")
    print(f" Target Panel: {target_panel}.panel")
    print(f" Location    : {button_folder}")
    print(f" Script File : {script_path}")
    print("=" * 60)

if __name__ == "__main__":
    deploy_tool_from_spec()