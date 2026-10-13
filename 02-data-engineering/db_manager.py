import sqlite3
from pathlib import Path
from datetime import datetime, timezone

# 1. Database file path configuration
DB_DIR = Path(__file__).resolve().parent
DB_PATH = DB_DIR / "bim_tools_vault.db"

def get_current_utc_timestamp() -> str:
    """Returns ISO format UTC timestamp avoiding deprecation warnings."""
    return datetime.now(timezone.utc).isoformat()

def init_database():
    """Initializes the SQLite database schema for tools and execution logs."""
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()

    # Table 1: Tools Registry (Core entity metadata)
    cursor.execute("""
    CREATE TABLE IF NOT EXISTS tools (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        name TEXT UNIQUE NOT NULL,
        target_panel TEXT NOT NULL,
        description TEXT,
        status TEXT CHECK(status IN ('PLANNED', 'CODED', 'REVIEWED', 'DEPLOYED', 'FAILED')) DEFAULT 'PLANNED',
        filesystem_path TEXT,
        created_at TEXT NOT NULL,
        updated_at TEXT NOT NULL
    );
    """)

    # Table 2: Generation Logs (Tracks agent iterations, timings, and outputs)
    cursor.execute("""
    CREATE TABLE IF NOT EXISTS generation_runs (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        tool_id INTEGER,
        agent_role TEXT NOT NULL,
        status TEXT NOT NULL,
        output_payload TEXT,
        error_message TEXT,
        duration_seconds REAL,
        timestamp TEXT NOT NULL,
        FOREIGN KEY (tool_id) REFERENCES tools(id) ON DELETE CASCADE
    );
    """)

    conn.commit()
    conn.close()

def register_tool(name: str, target_panel: str, description: str) -> int:
    """Inserts a new tool into the registry and returns its ID."""
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    now = get_current_utc_timestamp()

    try:
        cursor.execute("""
        INSERT INTO tools (name, target_panel, description, status, created_at, updated_at)
        VALUES (?, ?, ?, 'PLANNED', ?, ?)
        """, (name, target_panel, description, now, now))
        conn.commit()
        tool_id = cursor.lastrowid
        print(f"[REGISTERED] Tool '{name}' recorded with ID: {tool_id}")
        return tool_id
    except sqlite3.IntegrityError:
        cursor.execute("SELECT id FROM tools WHERE name = ?", (name,))
        tool_id = cursor.fetchone()[0]
        print(f"[EXISTS] Tool '{name}' already present in database (ID: {tool_id}).")
        return tool_id
    finally:
        conn.close()

def update_tool_status(tool_id: int, status: str, filesystem_path: str = None):
    """Updates the tool workflow status and optional deployed path."""
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    now = get_current_utc_timestamp()

    cursor.execute("""
    UPDATE tools
    SET status = ?, filesystem_path = COALESCE(?, filesystem_path), updated_at = ?
    WHERE id = ?
    """, (status, filesystem_path, now, tool_id))

    conn.commit()
    conn.close()
    print(f"[STATUS UPDATED] Tool ID {tool_id} -> {status}")

def log_agent_run(tool_id: int, agent_role: str, status: str, duration_seconds: float, payload: str = None, error_msg: str = None):
    """Records an execution snapshot from any agent in the pipeline."""
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    now = get_current_utc_timestamp()

    cursor.execute("""
    INSERT INTO generation_runs (tool_id, agent_role, status, output_payload, error_message, duration_seconds, timestamp)
    VALUES (?, ?, ?, ?, ?, ?, ?)
    """, (tool_id, agent_role, status, payload, error_msg, duration_seconds, now))

    conn.commit()
    conn.close()
    print(f"[LOGGED RUN] Agent: {agent_role} | Status: {status} | Elapsed: {duration_seconds}s")

def get_tool_records():
    """Fetches all tools and displays their current lifecycle status."""
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    cursor.execute("SELECT id, name, target_panel, status, filesystem_path FROM tools")
    rows = cursor.fetchall()
    conn.close()
    return rows

if __name__ == "__main__":
    init_database()
    tool_id = register_tool(
        name="Audit3DViewsWithoutWorksets",
        target_panel="Audit",
        description="Audits 3D views to verify assigned worksets."
    )
    # Test logging a reviewer agent run
    log_agent_run(
        tool_id=tool_id,
        agent_role="Architect",
        status="SUCCESS",
        duration_seconds=2.45,
        payload="Pydantic specs validated."
    )
    # Test status progression
    update_tool_status(tool_id, "DEPLOYED", filesystem_path="output_extensions/.../Audit3DViewsWithoutWorksets.pushbutton")

    print("\n--- Current Registered Tools ---")
    for row in get_tool_records():
        print(row)