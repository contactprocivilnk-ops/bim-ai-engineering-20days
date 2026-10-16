import sqlite3
import json
import argparse
from pathlib import Path
from datetime import datetime

DB_PATH = Path(__file__).resolve().parent / "bim_tools_vault.db"

def get_connection():
    if not DB_PATH.exists():
        raise FileNotFoundError(f"Database file not found at: {DB_PATH}")
    return sqlite3.connect(DB_PATH)

def list_all_tools():
    """Prints a structured summary table of all registered pyRevit tools."""
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute("""
        SELECT id, name, target_panel, status, updated_at 
        FROM tools 
        ORDER BY id ASC
    """)
    rows = cursor.fetchall()
    conn.close()

    print("\n" + "=" * 80)
    print(f"{'ID':<4} | {'Tool Name':<30} | {'Panel':<15} | {'Status':<10} | {'Last Updated'}")
    print("-" * 80)
    for row in rows:
        print(f"{row[0]:<4} | {row[1]:<30} | {row[2]:<15} | {row[3]:<10} | {row[4]}")
    print("=" * 80 + f"\nTotal Tools: {len(rows)}\n")

def inspect_tool(tool_id: int):
    """Displays detailed execution runs and outputs for a specific tool ID."""
    conn = get_connection()
    cursor = conn.cursor()

    cursor.execute("SELECT id, name, target_panel, status, filesystem_path, description FROM tools WHERE id = ?", (tool_id,))
    tool = cursor.fetchone()

    if not tool:
        print(f"[ERROR] No tool found with ID: {tool_id}")
        conn.close()
        return

    print("\n" + "=" * 80)
    print(f" TOOL AUDIT: #{tool[0]} - {tool[1]}")
    print(f" Target Panel : {tool[2]}")
    print(f" Current Status: {tool[3]}")
    print(f" Deployed Path : {tool[4] or 'Not Deployed'}")
    print(f" Description   : {tool[5]}")
    print("-" * 80)
    print(" Execution Runs History:")

    cursor.execute("""
        SELECT agent_role, status, duration_seconds, timestamp, error_message, output_payload
        FROM generation_runs
        WHERE tool_id = ?
        ORDER BY id ASC
    """, (tool_id,))
    runs = cursor.fetchall()
    conn.close()

    if not runs:
        print("  (No agent execution logs found for this tool)")
    else:
        for r in runs:
            agent, st, duration, ts, err, payload = r
            print(f"  [{ts}] Agent: {agent:<12} | Status: {st:<8} | Latency: {duration:>6.2f}s")
            if err:
                print(f"     -> Error: {err}")
            if payload and len(payload) > 80:
                print(f"     -> Payload Preview: {payload[:75]}...")
    print("=" * 80 + "\n")

def display_agent_metrics():
    """Calculates latency benchmarks per agent role across all generation runs."""
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute("""
        SELECT 
            agent_role,
            COUNT(*) as total_calls,
            SUM(CASE WHEN status = 'SUCCESS' THEN 1 ELSE 0 END) as success_calls,
            AVG(duration_seconds) as avg_latency,
            MAX(duration_seconds) as max_latency
        FROM generation_runs
        WHERE duration_seconds > 0
        GROUP BY agent_role
    """)
    rows = cursor.fetchall()
    conn.close()

    print("\n" + "=" * 80)
    print(" AGENT PERFORMANCE & LATENCY METRICS")
    print("-" * 80)
    print(f"{'Agent Role':<15} | {'Calls':<6} | {'Success Rate':<14} | {'Avg Latency':<12} | {'Max Latency'}")
    print("-" * 80)
    for row in rows:
        role, total, success, avg_lat, max_lat = row
        rate = f"{(success / total) * 100:.1f}%" if total > 0 else "0.0%"
        print(f"{role:<15} | {total:<6} | {rate:<14} | {avg_lat:>9.2f}s | {max_lat:>9.2f}s")
    print("=" * 80 + "\n")

def export_audit_json(output_file: str = "vault_audit_export.json"):
    """Exports full database state to a JSON report for architectural auditing."""
    conn = get_connection()
    conn.row_factory = sqlite3.Row
    cursor = conn.cursor()

    cursor.execute("SELECT * FROM tools")
    tools = [dict(row) for row in cursor.fetchall()]

    cursor.execute("SELECT * FROM generation_runs")
    runs = [dict(row) for row in cursor.fetchall()]
    conn.close()

    report = {
        "generated_at": datetime.utcnow().isoformat() + "Z",
        "total_tools": len(tools),
        "total_agent_runs": len(runs),
        "tools": tools,
        "runs": runs
    }

    out_path = Path(__file__).resolve().parent / output_file
    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(report, f, indent=2)

    print(f"[EXPORTED] Full vault audit report saved to: {out_path}")

def main():
    parser = argparse.ArgumentParser(description="BIM AI Tool Vault Inspector & Metrics CLI")
    parser.add_argument("--list", action="store_true", help="List all registered pyRevit tools")
    parser.add_argument("--tool", type=int, help="Inspect full history of a tool by its ID")
    parser.add_argument("--metrics", action="store_true", help="Display agent latency and success metrics")
    parser.add_argument("--export", action="store_true", help="Export audit report to JSON")

    args = parser.parse_args()

    # Default action if no flags passed: show both list and metrics
    if not (args.list or args.tool or args.metrics or args.export):
        list_all_tools()
        display_agent_metrics()
        return

    if args.list:
        list_all_tools()
    if args.tool:
        inspect_tool(args.tool)
    if args.metrics:
        display_agent_metrics()
    if args.export:
        export_audit_json()

if __name__ == "__main__":
    main()