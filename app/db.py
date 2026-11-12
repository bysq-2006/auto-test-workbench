"""SQLite schema and skill sync. One local file, no external database."""

import ast
import sqlite3
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SKILLS_DIR = ROOT / "skills"

SCHEMA = (
    """
    CREATE TABLE IF NOT EXISTS skills (
        id INTEGER PRIMARY KEY,
        name TEXT NOT NULL,
        description TEXT NOT NULL DEFAULT '',
        path TEXT NOT NULL UNIQUE
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS tasks (
        id INTEGER PRIMARY KEY,
        title TEXT NOT NULL,
        status TEXT NOT NULL CHECK (status IN ('pending', 'running', 'done', 'failed')),
        assignee TEXT,
        skill_id INTEGER REFERENCES skills(id) ON DELETE SET NULL,
        payload TEXT,
        created_at TEXT NOT NULL,
        updated_at TEXT NOT NULL
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS test_results (
        id INTEGER PRIMARY KEY,
        agent_name TEXT NOT NULL,
        task_id INTEGER REFERENCES tasks(id) ON DELETE SET NULL,
        skill_id INTEGER REFERENCES skills(id) ON DELETE SET NULL,
        status TEXT NOT NULL CHECK (status IN ('pass', 'fail')),
        summary TEXT NOT NULL DEFAULT '',
        log_text TEXT NOT NULL DEFAULT '',
        created_at TEXT NOT NULL
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS messages (
        id INTEGER PRIMARY KEY,
        kind TEXT NOT NULL CHECK (kind IN ('message', 'claim')),
        from_agent TEXT NOT NULL,
        to_agent TEXT,
        body TEXT NOT NULL DEFAULT '',
        resource_name TEXT,
        status TEXT NOT NULL,
        created_at TEXT NOT NULL,
        updated_at TEXT NOT NULL,
        CHECK (
            (kind = 'message' AND status = 'sent' AND resource_name IS NULL)
            OR (kind = 'claim' AND status IN ('held', 'released') AND resource_name IS NOT NULL)
        )
    )
    """,
    "CREATE INDEX IF NOT EXISTS idx_tasks_status ON tasks(status)",
    "CREATE INDEX IF NOT EXISTS idx_results_status ON test_results(status)",
    # Only one agent may hold a given resource. A second INSERT fails.
    """
    CREATE UNIQUE INDEX IF NOT EXISTS idx_one_holder
    ON messages(resource_name)
    WHERE kind = 'claim' AND status = 'held'
    """,
)


def utcnow() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def db_path() -> Path:
    import os

    return Path(os.environ.get("WORKBENCH_DB", ROOT / "data" / "workbench.db"))


def connect() -> sqlite3.Connection:
    path = db_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    # isolation_level None = autocommit. Callers that must be atomic use BEGIN IMMEDIATE.
    conn = sqlite3.connect(path, isolation_level=None)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    return conn


def init_db(conn: sqlite3.Connection) -> None:
    for statement in SCHEMA:
        conn.execute(statement)


def _docstring(source: str) -> str:
    try:
        doc = ast.get_docstring(ast.parse(source))
    except SyntaxError:
        return ""
    return (doc or "").strip()


def sync_skills(conn: sqlite3.Connection) -> None:
    """Register each skills/*.py file. The module docstring is the usage text."""
    found = []
    if SKILLS_DIR.is_dir():
        for path in sorted(SKILLS_DIR.glob("*.py")):
            rel = path.relative_to(ROOT).as_posix()
            found.append(rel)
            name = path.stem
            description = _docstring(path.read_text(encoding="utf-8"))
            existing = conn.execute("SELECT id FROM skills WHERE path = ?", (rel,)).fetchone()
            if existing:
                conn.execute(
                    "UPDATE skills SET name = ?, description = ? WHERE id = ?",
                    (name, description, existing["id"]),
                )
            else:
                conn.execute(
                    "INSERT INTO skills (name, description, path) VALUES (?, ?, ?)",
                    (name, description, rel),
                )
    for row in conn.execute("SELECT id, path FROM skills").fetchall():
        if row["path"] not in found:
            conn.execute("DELETE FROM skills WHERE id = ?", (row["id"],))
