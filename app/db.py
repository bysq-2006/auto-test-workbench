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
        status TEXT NOT NULL CHECK (status IN ('idle', 'occupied', 'closed')),
        agent_name TEXT,
        pid INTEGER,
        user_data_dir TEXT,
        created_at TEXT NOT NULL,
        updated_at TEXT NOT NULL
    )
    """,
    "CREATE INDEX IF NOT EXISTS idx_results_status ON test_results(status)",
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


def _tables(conn: sqlite3.Connection) -> set[str]:
    return {row[0] for row in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")}


def _columns(conn: sqlite3.Connection, table: str) -> list[str]:
    return [row[1] for row in conn.execute(f"PRAGMA table_info({table})")]


def _migrate_skills_off_db(conn: sqlite3.Connection) -> None:
    """旧库若还有 skills 表和 skill_id，改成文本路径 skill_path，然后丢掉技能表。"""
    tables = _tables(conn)
    need_tasks = "tasks" in tables and "skill_id" in _columns(conn, "tasks")
    need_results = "test_results" in tables and "skill_id" in _columns(conn, "test_results")
    need_drop = "skills" in tables
    if not (need_tasks or need_results or need_drop):
        return

    conn.execute("PRAGMA foreign_keys = OFF")
    has_skills = "skills" in tables

    if need_tasks:
        if has_skills:
            conn.execute(
                """
                CREATE TABLE tasks_new (
                    id INTEGER PRIMARY KEY,
                    title TEXT NOT NULL,
                    status TEXT NOT NULL CHECK (status IN ('pending', 'running', 'done', 'failed')),
                    agent_name TEXT,
                    skill_path TEXT,
                    payload TEXT,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                )
                """
            )
            conn.execute(
                """
                INSERT INTO tasks_new (id, title, status, agent_name, skill_path, payload, created_at, updated_at)
                SELECT tasks.id, tasks.title, tasks.status, tasks.assignee,
                       (SELECT path FROM skills WHERE skills.id = tasks.skill_id),
                       tasks.payload, tasks.created_at, tasks.updated_at
                FROM tasks
                """
            )
        else:
            conn.execute(
                """
                CREATE TABLE tasks_new (
                    id INTEGER PRIMARY KEY,
                    title TEXT NOT NULL,
                    status TEXT NOT NULL CHECK (status IN ('pending', 'running', 'done', 'failed')),
                    agent_name TEXT,
                    skill_path TEXT,
                    payload TEXT,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                )
                """
            )
            conn.execute(
                """
                INSERT INTO tasks_new (id, title, status, agent_name, skill_path, payload, created_at, updated_at)
                SELECT id, title, status, assignee, NULL, payload, created_at, updated_at
                FROM tasks
                """
            )
        conn.execute("DROP TABLE tasks")
        conn.execute("ALTER TABLE tasks_new RENAME TO tasks")
        conn.execute("CREATE INDEX IF NOT EXISTS idx_tasks_status ON tasks(status)")

    if need_results:
        conn.execute(
            """
            CREATE TABLE test_results_new (
                id INTEGER PRIMARY KEY,
                agent_name TEXT NOT NULL,
                task_id INTEGER REFERENCES tasks(id) ON DELETE SET NULL,
                skill_path TEXT,
                status TEXT NOT NULL CHECK (status IN ('pass', 'fail')),
                summary TEXT NOT NULL DEFAULT '',
                log_text TEXT NOT NULL DEFAULT '',
                created_at TEXT NOT NULL
            )
            """
        )
        if has_skills:
            conn.execute(
                """
                INSERT INTO test_results_new
                    (id, agent_name, task_id, skill_path, status, summary, log_text, created_at)
                SELECT test_results.id, test_results.agent_name, test_results.task_id,
                       (SELECT path FROM skills WHERE skills.id = test_results.skill_id),
                       test_results.status, test_results.summary, test_results.log_text,
                       test_results.created_at
                FROM test_results
                """
            )
        else:
            conn.execute(
                """
                INSERT INTO test_results_new
                    (id, agent_name, task_id, skill_path, status, summary, log_text, created_at)
                SELECT id, agent_name, task_id, NULL, status, summary, log_text, created_at
                FROM test_results
                """
            )
        conn.execute("DROP TABLE test_results")
        conn.execute("ALTER TABLE test_results_new RENAME TO test_results")
        conn.execute("CREATE INDEX IF NOT EXISTS idx_results_status ON test_results(status)")

    if "skills" in _tables(conn):
        conn.execute("DROP TABLE skills")
    conn.execute("PRAGMA foreign_keys = ON")



def _migrate_results_generic(conn: sqlite3.Connection) -> None:
    """旧的测试结果表加上 kind，状态改为仅测试必填。"""
    if "test_results" not in _tables(conn):
        return
    if "kind" in _columns(conn, "test_results"):
        return
    conn.execute("PRAGMA foreign_keys = OFF")
    conn.execute(
        """
        CREATE TABLE test_results_new (
            id INTEGER PRIMARY KEY,
            agent_name TEXT NOT NULL,
            kind TEXT NOT NULL DEFAULT 'test' CHECK (kind IN ('test', 'note')),
            task_id INTEGER REFERENCES tasks(id) ON DELETE SET NULL,
            skill_path TEXT,
            status TEXT CHECK (status IS NULL OR status IN ('pass', 'fail')),
            summary TEXT NOT NULL DEFAULT '',
            log_text TEXT NOT NULL DEFAULT '',
            created_at TEXT NOT NULL,
            CHECK (
                (kind = 'test' AND status IN ('pass', 'fail'))
                OR (kind = 'note' AND status IS NULL)
            )
        )
        """
    )
    conn.execute(
        """
        INSERT INTO test_results_new
            (id, agent_name, kind, task_id, skill_path, status, summary, log_text, created_at)
        SELECT id, agent_name, 'test', task_id, skill_path, status, summary, log_text, created_at
        FROM test_results
        """
    )
    conn.execute("DROP TABLE test_results")
    conn.execute("ALTER TABLE test_results_new RENAME TO test_results")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_results_status ON test_results(status)")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_results_kind ON test_results(kind)")
    conn.execute("PRAGMA foreign_keys = ON")



def _migrate_drop_claims(conn: sqlite3.Connection) -> None:
    """去掉资源占用：删掉 claim 记录，消息表只保留发送者和正文。"""
    if "messages" not in _tables(conn):
        return
    cols = _columns(conn, "messages")
    if "kind" not in cols and "resource_name" not in cols:
        return
    conn.execute("PRAGMA foreign_keys = OFF")
    conn.execute(
        """
        CREATE TABLE messages_new (
            id INTEGER PRIMARY KEY,
            from_agent TEXT NOT NULL DEFAULT '',
            body TEXT NOT NULL DEFAULT '',
            created_at TEXT NOT NULL
        )
        """
    )
    if "kind" in cols:
        conn.execute(
            """
            INSERT INTO messages_new (id, from_agent, body, created_at)
            SELECT id, IFNULL(from_agent, ''), body, created_at
            FROM messages
            WHERE kind = 'message' OR kind IS NULL
            """
        )
    else:
        conn.execute(
            """
            INSERT INTO messages_new (id, from_agent, body, created_at)
            SELECT id, IFNULL(from_agent, ''), body, created_at
            FROM messages
            """
        )
    conn.execute("DROP TABLE messages")
    conn.execute("ALTER TABLE messages_new RENAME TO messages")
    conn.execute("PRAGMA foreign_keys = ON")



def _migrate_task_agent_name(conn: sqlite3.Connection) -> None:
    """任务表里原来的 assignee 和结果表的 agent_name 是同一个意思，统一成 agent_name。"""
    if "tasks" not in _tables(conn):
        return
    cols = _columns(conn, "tasks")
    if "agent_name" in cols or "assignee" not in cols:
        return
    conn.execute("ALTER TABLE tasks RENAME COLUMN assignee TO agent_name")




def _migrate_task_description(conn: sqlite3.Connection) -> None:
    """任务表加上 description，给任务写说明。"""
    if "tasks" not in _tables(conn):
        return
    if "description" in _columns(conn, "tasks"):
        return
    conn.execute("ALTER TABLE tasks ADD COLUMN description TEXT NOT NULL DEFAULT ''")


def _migrate_results_recorded(conn: sqlite3.Connection) -> None:
    """结果表加上 recorded，表示主 AI 是否已经记录过这条。"""
    if "test_results" not in _tables(conn):
        return
    if "recorded" in _columns(conn, "test_results"):
        return
    conn.execute(
        "ALTER TABLE test_results ADD COLUMN recorded INTEGER NOT NULL DEFAULT 0 CHECK (recorded IN (0, 1))"
    )


def init_db(conn: sqlite3.Connection) -> None:
    _migrate_skills_off_db(conn)
    _migrate_results_generic(conn)
    _migrate_drop_claims(conn)
    _migrate_task_agent_name(conn)
    _migrate_task_description(conn)
    _migrate_results_recorded(conn)
    for statement in SCHEMA:
        conn.execute(statement)
    conn.execute("CREATE INDEX IF NOT EXISTS idx_results_kind ON test_results(kind)")
