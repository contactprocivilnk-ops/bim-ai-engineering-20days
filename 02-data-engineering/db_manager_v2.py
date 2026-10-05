import logging
import sqlite3
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

log = logging.getLogger("db_manager")

DB_DIR = Path(__file__).resolve().parent
DB_PATH = DB_DIR / "bim_tools_vault.db"

TOOL_STATUSES = ("PLANNED", "CODED", "REVIEWED", "DEPLOYED", "FAILED")
RUN_STATUSES = ("SUCCESS", "FAILED", "SKIPPED")


def get_current_utc_timestamp() -> str:
    return datetime.now(timezone.utc).isoformat()


@contextmanager
def _connect():
    """Connection that is ALWAYS closed; commits on success, rolls back on error.

    NOTE: `with sqlite3.connect(...) as conn` alone only manages the
    transaction - it does NOT close the connection.
    """
    conn = sqlite3.connect(DB_PATH, timeout=30)
    try:
        conn.execute("PRAGMA foreign_keys = ON")      # off by default in SQLite
        conn.execute("PRAGMA busy_timeout = 30000")
        with conn:
            yield conn
    finally:
        conn.close()


def init_database() -> None:
    with _connect() as conn:
        conn.execute("PRAGMA journal_mode = WAL")      # persistent, fewer lock errors
        conn.execute("""
        CREATE TABLE IF NOT EXISTS tools (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT UNIQUE NOT NULL,
            target_panel TEXT NOT NULL,
            description TEXT,
            status TEXT CHECK(status IN ('PLANNED','CODED','REVIEWED','DEPLOYED','FAILED'))
                DEFAULT 'PLANNED',
            filesystem_path TEXT,
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL
        )""")
        conn.execute("""
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
        )""")


def register_tool(name: str, target_panel: str, description: str) -> int:
    """Insert, or on a name clash refresh the metadata and reset to PLANNED."""
    now = get_current_utc_timestamp()
    with _connect() as conn:
        conn.execute("""
        INSERT INTO tools (name, target_panel, description, status, created_at, updated_at)
        VALUES (?, ?, ?, 'PLANNED', ?, ?)
        ON CONFLICT(name) DO UPDATE SET
            target_panel = excluded.target_panel,
            description  = excluded.description,
            status       = 'PLANNED',
            updated_at   = excluded.updated_at
        """, (name, target_panel, description, now, now))
        row = conn.execute("SELECT id FROM tools WHERE name = ?", (name,)).fetchone()
    log.info("Tool %r registered (ID %s)", name, row[0])
    return row[0]


def update_tool_status(tool_id: int, status: str, filesystem_path: Optional[str] = None) -> None:
    if status not in TOOL_STATUSES:
        raise ValueError("Invalid tool status: {!r}".format(status))
    with _connect() as conn:
        cur = conn.execute("""
        UPDATE tools
        SET status = ?, filesystem_path = COALESCE(?, filesystem_path), updated_at = ?
        WHERE id = ?
        """, (status, filesystem_path, get_current_utc_timestamp(), tool_id))
        if cur.rowcount != 1:
            raise LookupError("No tool with id {}".format(tool_id))
    log.info("Tool %s -> %s", tool_id, status)


def log_agent_run(tool_id: Optional[int], agent_role: str, status: str,
                  duration_seconds: float, payload: Optional[str] = None,
                  error_msg: Optional[str] = None) -> None:
    """tool_id may be None for failures that happen before registration."""
    if status not in RUN_STATUSES:
        raise ValueError("Invalid run status: {!r}".format(status))
    with _connect() as conn:
        conn.execute("""
        INSERT INTO generation_runs
            (tool_id, agent_role, status, output_payload, error_message, duration_seconds, timestamp)
        VALUES (?, ?, ?, ?, ?, ?, ?)
        """, (tool_id, agent_role, status, payload, error_msg,
              round(duration_seconds, 3), get_current_utc_timestamp()))


def mark_failed(tool_id: Optional[int], stage: str, error_text: str,
                duration_seconds: float = 0.0) -> None:
    """Tool -> FAILED and the full traceback persisted in ONE transaction."""
    now = get_current_utc_timestamp()
    with _connect() as conn:
        if tool_id is not None:
            conn.execute("UPDATE tools SET status = 'FAILED', updated_at = ? WHERE id = ?",
                         (now, tool_id))
        conn.execute("""
        INSERT INTO generation_runs
            (tool_id, agent_role, status, output_payload, error_message, duration_seconds, timestamp)
        VALUES (?, ?, 'FAILED', NULL, ?, ?, ?)
        """, (tool_id, stage, error_text, round(duration_seconds, 3), now))


def get_tool_records():
    with _connect() as conn:
        return conn.execute(
            "SELECT id, name, target_panel, status, filesystem_path FROM tools").fetchall()
