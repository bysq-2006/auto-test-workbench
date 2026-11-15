"""SQLite 库文件和表结构。技能不入库，只扫 skills/ 目录。"""

import sqlite3
import threading
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path

# 所有请求共用这一把锁，避免并发写坏同一个库文件
_lock = threading.Lock()

ROOT = Path(__file__).resolve().parent.parent
SKILLS_DIR = ROOT / "skills"

SCHEMA = (
    """
    CREATE TABLE IF NOT EXISTS tasks (
        id INTEGER PRIMARY KEY,
        title TEXT NOT NULL,
        description TEXT NOT NULL DEFAULT '',
        status TEXT NOT NULL CHECK (status IN ('pending', 'running', 'done', 'failed')),
        agent_name TEXT,
        skill_path TEXT,
        payload TEXT,
        created_at TEXT NOT NULL,
        updated_at TEXT NOT NULL
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS test_results (
        id INTEGER PRIMARY KEY,
        agent_name TEXT NOT NULL,
        kind TEXT NOT NULL DEFAULT 'test' CHECK (kind IN ('test', 'note')),
        task_id INTEGER REFERENCES tasks(id) ON DELETE SET NULL,
        skill_path TEXT,
        status TEXT CHECK (status IS NULL OR status IN ('pass', 'fail')),
        summary TEXT NOT NULL DEFAULT '',
        log_text TEXT NOT NULL DEFAULT '',
        recorded INTEGER NOT NULL DEFAULT 0 CHECK (recorded IN (0, 1)),
        created_at TEXT NOT NULL,
        CHECK (
            (kind = 'test' AND status IN ('pass', 'fail'))
            OR (kind = 'note' AND status IS NULL)
        )
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS messages (
        id INTEGER PRIMARY KEY,
        from_agent TEXT NOT NULL DEFAULT '',
        body TEXT NOT NULL DEFAULT '',
        created_at TEXT NOT NULL
    )
    """,
    "CREATE INDEX IF NOT EXISTS idx_tasks_status ON tasks(status)",
    """
    CREATE TABLE IF NOT EXISTS browsers (
        id INTEGER PRIMARY KEY,
        port INTEGER NOT NULL,
        name TEXT NOT NULL DEFAULT '',
        status TEXT NOT NULL CHECK (status IN ('idle', 'occupied', 'closed')),
        agent_name TEXT,
        pid INTEGER,
        user_data_dir TEXT,
        created_at TEXT NOT NULL,
        updated_at TEXT NOT NULL
    )
    """,
    "CREATE INDEX IF NOT EXISTS idx_results_status ON test_results(status)",
    "CREATE INDEX IF NOT EXISTS idx_results_kind ON test_results(kind)",
)


def utcnow() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def db_path() -> Path:
    # 库固定放在项目 data/ 下，不提供改路径的开关，免得两份库分叉
    return ROOT / "data" / "workbench.db"


def connect() -> sqlite3.Connection:
    path = db_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    # isolation_level=None 表示自动提交；需要原子操作的接口自己 BEGIN IMMEDIATE
    # timeout/WAL：页面会同时打多个接口，默认 timeout=0 容易直接 500
    # check_same_thread=False：FastAPI 可能在不同线程里使用/关闭同一条连接
    conn = sqlite3.connect(path, isolation_level=None, timeout=30.0, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA busy_timeout=30000")
    return conn


@contextmanager
def locked_connect():
    """拿连接期间占用全局锁，用完立刻关掉。"""
    with _lock:
        conn = connect()
        try:
            yield conn
        finally:
            conn.close()


def init_db(conn: sqlite3.Connection) -> None:
    for statement in SCHEMA:
        conn.execute(statement)
