import os
import ast
import sqlite3
import argparse
from pathlib import Path
from datetime import datetime, timezone

DB_PATH = Path(__file__).resolve().parent / "bim_tools_vault.db"
EXTENSIONS_ROOT = Path(__file__).resolve().parent / "output_extensions"

def get_current_utc_timestamp() -> str:
    return datetime.now(timezone.utc).isoformat()

def get_connection():
    if not DB_PATH.exists():
        raise FileNotFoundError(f"Database not found at: {DB_PATH}")
    return sqlite3.connect(DB_PATH)

def validate_python_syntax(file_path: Path) -> tuple[bool, str]:
    """Compiles Python script into an Abstract Syntax Tree to ensure syntax validity."""
    try:
        with open(file_path, "r", encoding="utf-8") as f:
            source = f.read()
        ast.parse(source)
        return True, "Syntax Valid"
    except SyntaxError as e:
        return False, f"Syntax Error on line {e.lineno}: {e.msg}"
    except Exception as e:
        return False, f"File read error: {str(e)}"

def reconcile_vault():
    """Performs bidirectional audit between SQLite records and physical filesystem."""
    conn = get_connection()
    cursor = conn.cursor()

    print("\n" + "=" * 80)
    print(" STARTING VAULT & FILESYSTEM RECONCILIATION")
    print("=" * 80)

    # 1. Audit Registered Tools
    cursor.execute("SELECT id, name, status, filesystem_path FROM tools")
    registered_tools = cursor.fetchall()

    registered_paths = set()
    verified_count = 0
    missing_count = 0
    syntax_error_count = 0

    print("\n[Phase 1/2] Auditing Database Records against Disk...")
    for tool_id, name, status, fs_path in registered_tools:
        if not fs_path:
            print(f"  [ID {tool_id}] {name:<30} -> NO PATH RECORDED")
            continue

        p = Path(fs_path)
        registered_paths.add(p.resolve())
        script_file = p / "script.py"

        if not p.exists() or not script_file.exists():
            print(f"  [ID {tool_id}] {name:<30} -> [MISSING ON DISK]")
            cursor.execute("""
                UPDATE tools SET status = 'FAILED', updated_at = ? WHERE id = ?
            """, (get_current_utc_timestamp(), tool_id))
            missing_count += 1
            continue

        # Check Syntax Integrity
        is_valid, msg = validate_python_syntax(script_file)
        if not is_valid:
            print(f"  [ID {tool_id}] {name:<30} -> [SYNTAX ERROR] {msg}")
            cursor.execute("""
                UPDATE tools SET status = 'FAILED', updated_at = ? WHERE id = ?
            """, (get_current_utc_timestamp(), tool_id))
            syntax_error_count += 1
        else:
            print(f"  [ID {tool_id}] {name:<30} -> [VERIFIED HEALTHY]")
            cursor.execute("""
                UPDATE tools SET status = 'DEPLOYED', updated_at = ? WHERE id = ?
            """, (get_current_utc_timestamp(), tool_id))
            verified_count += 1

    # 2. Discover Orphan Tools on Disk
    print("\n[Phase 2/2] Scanning for Unregistered / Orphan pyRevit Tools on Disk...")
    orphan_count = 0

    if EXTENSIONS_ROOT.exists():
        for pushbutton in EXTENSIONS_ROOT.glob("**/*.pushbutton"):
            resolved_button = pushbutton.resolve()
            if resolved_button not in registered_paths:
                tool_name = pushbutton.stem
                parent_panel = pushbutton.parent.stem.replace(".panel", "")
                now = get_current_utc_timestamp()

                print(f"  [DISCOVERED ORPHAN] Found: {tool_name} in {parent_panel}.panel")
                
                # Check syntax of orphan
                script_file = pushbutton / "script.py"
                is_valid, _ = validate_python_syntax(script_file) if script_file.exists() else (False, "No script")
                initial_status = "DEPLOYED" if is_valid else "FAILED"

                cursor.execute("""
                    INSERT INTO tools (name, target_panel, description, status, filesystem_path, created_at, updated_at)
                    VALUES (?, ?, 'Auto-discovered from filesystem', ?, ?, ?, ?)
                """, (tool_name, parent_panel, initial_status, str(pushbutton), now, now))
                orphan_count += 1

    conn.commit()
    conn.close()

    print("\n" + "=" * 80)
    print(" RECONCILIATION SUMMARY")
    print(f"  Verified & Healthy Tools : {verified_count}")
    print(f"  Missing from Disk        : {missing_count}")
    print(f"  Syntax Errors Flagged    : {syntax_error_count}")
    print(f"  Orphan Tools Registered  : {orphan_count}")
    print("=" * 80 + "\n")

if __name__ == "__main__":
    reconcile_vault()