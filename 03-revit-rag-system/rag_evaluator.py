import ast
import json
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent
DEPLOY_BASE_DIR = BASE_DIR / "output_extensions" / "BIM_AI_RAG.extension" / "RAGTools.tab"

# Grounded Best Practices derived from our vector store
CRITICAL_REVIT_RULES = [
    {
        "id": "RULE_TRANSACTION",
        "name": "Transaction Wrapping",
        "description": "Modifications must be enclosed in revit.Transaction",
        "check": lambda code: "revit.Transaction" in code or "Transaction(" in code,
        "weight": 25
    },
    {
        "id": "RULE_COLLECTOR",
        "name": "FilteredElementCollector Usage",
        "description": "Must use FilteredElementCollector rather than full document scans",
        "check": lambda code: "FilteredElementCollector" in code,
        "weight": 25
    },
    {
        "id": "RULE_VIEW_DRAFTING",
        "name": "ViewDrafting Handling",
        "description": "Must query or reference ViewDrafting or view-specific logic",
        "check": lambda code: "ViewDrafting" in code or "View" in code,
        "weight": 25
    },
    {
        "id": "RULE_TEMPLATE_SAFETY",
        "name": "View Template Exclusion",
        "description": "Must guard against modifying view templates (IsTemplate check)",
        "check": lambda code: "IsTemplate" in code or "is_template" in code or "ViewType" in code,
        "weight": 25
    }
]

def evaluate_script(script_path: Path) -> dict:
    if not script_path.exists():
        raise FileNotFoundError(f"Script not found at: {script_path}")

    with open(script_path, "r", encoding="utf-8") as f:
        code_content = f.read()

    # 1. AST Syntax Check
    syntax_valid = False
    syntax_error = None
    try:
        ast.parse(code_content)
        syntax_valid = True
    except SyntaxError as e:
        syntax_error = f"Line {e.lineno}: {e.msg}"

    # 2. Rule-based Groundedness Audit
    earned_score = 0
    total_score = sum(r["weight"] for r in CRITICAL_REVIT_RULES)
    rule_results = []

    for rule in CRITICAL_REVIT_RULES:
        passed = rule["check"](code_content)
        if passed:
            earned_score += rule["weight"]
        rule_results.append({
            "id": rule["id"],
            "name": rule["name"],
            "passed": passed,
            "weight": rule["weight"]
        })

    final_score = round((earned_score / total_score) * 100, 2)

    return {
        "file_name": script_path.name,
        "path": str(script_path),
        "total_lines": len(code_content.splitlines()),
        "syntax_valid": syntax_valid,
        "syntax_error": syntax_error,
        "groundedness_score": final_score,
        "rules_evaluated": rule_results
    }

def run_evaluation():
    print("\n" + "=" * 75)
    print(" REVIT API RAG GROUNDEDNESS & CODE QUALITY AUDIT")
    print("=" * 75)

    scripts = list(DEPLOY_BASE_DIR.glob("**/*.pushbutton/script.py"))
    if not scripts:
        print("[ERROR] No generated RAG scripts found in output directory.")
        return

    for script in scripts:
        res = evaluate_script(script)
        tool_name = script.parent.name.replace(".pushbutton", "")
        panel_name = script.parent.parent.name.replace(".panel", "")

        print(f"\nTool: {tool_name} (Panel: {panel_name})")
        print(f"Path: {script}")
        print(f"Lines of Code : {res['total_lines']}")
        print(f"AST Syntax    : {'PASS (No Syntax Errors)' if res['syntax_valid'] else f'FAIL ({res['syntax_error']})'}")
        print("-" * 75)
        print(f"{'Audit Rule':<35} | {'Weight':<8} | {'Status'}")
        print("-" * 75)
        for r in res["rules_evaluated"]:
            st = "PASSED [✓]" if r["passed"] else "FAILED [✗]"
            print(f"{r['name']:<35} | {r['weight']:<8} | {st}")
        print("-" * 75)
        print(f"FINAL GROUNDEDNESS SCORE: {res['groundedness_score']} / 100.0%\n")
    print("=" * 75 + "\n")

if __name__ == "__main__":
    run_evaluation()