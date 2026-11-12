"""Multi-agent test workbench. Tasks, skills, results, and resource claims."""

import json
import sqlite3
from contextlib import asynccontextmanager
from typing import Any, Literal

from fastapi import Depends, FastAPI, HTTPException, Query
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from app.db import ROOT, connect, init_db, sync_skills, utcnow

STATIC = ROOT / "static"


class UTF8JSONResponse(JSONResponse):
    def render(self, content: Any) -> bytes:
        return json.dumps(content, ensure_ascii=False).encode("utf-8")


@asynccontextmanager
async def lifespan(_app: FastAPI):
    conn = connect()
    try:
        init_db(conn)
        sync_skills(conn)
    finally:
        conn.close()
    yield


app = FastAPI(title="Auto Test Workbench", default_response_class=UTF8JSONResponse, lifespan=lifespan)
app.mount("/static", StaticFiles(directory=STATIC), name="static")


def get_conn():
    conn = connect()
    try:
        yield conn
    finally:
        conn.close()


def dump_payload(value: Any) -> str | None:
    if value is None:
        return None
    if isinstance(value, str):
        return value
    return json.dumps(value, ensure_ascii=False)


class TaskIn(BaseModel):
    title: str = Field(min_length=1)
    skill_id: int | None = None
    payload: Any = None


class TaskClaimIn(BaseModel):
    assignee: str = Field(min_length=1)


class TaskStatusIn(BaseModel):
    status: Literal["pending", "running", "done", "failed"]
    assignee: str | None = None


class ResultIn(BaseModel):
    agent_name: str = Field(min_length=1)
    task_id: int | None = None
    skill_id: int | None = None
    status: Literal["pass", "fail"]
    summary: str = ""
    log_text: str = ""


class MessageIn(BaseModel):
    from_agent: str = Field(min_length=1)
    to_agent: str | None = None
    body: str = Field(min_length=1)


class ClaimIn(BaseModel):
    resource: str = Field(min_length=1)
    owner: str = Field(min_length=1)
    note: str = ""


class ReleaseIn(BaseModel):
    resource: str = Field(min_length=1)
    owner: str = Field(min_length=1)


def _task(conn: sqlite3.Connection, task_id: int) -> dict:
    row = conn.execute(
        """
        SELECT tasks.*, skills.name AS skill_name, skills.path AS skill_path
        FROM tasks LEFT JOIN skills ON skills.id = tasks.skill_id
        WHERE tasks.id = ?
        """,
        (task_id,),
    ).fetchone()
    if row is None:
        raise HTTPException(404, "task not found")
    return dict(row)


def _claim_view(row: sqlite3.Row) -> dict:
    return {
        "id": row["id"],
        "resource": row["resource_name"],
        "owner": row["from_agent"],
        "status": row["status"],
        "note": row["body"],
        "created_at": row["created_at"],
        "updated_at": row["updated_at"],
    }


@app.get("/")
def index():
    return FileResponse(STATIC / "index.html")


@app.get("/skills")
def list_skills(conn: sqlite3.Connection = Depends(get_conn)):
    rows = conn.execute("SELECT id, name, description, path FROM skills ORDER BY id").fetchall()
    return [dict(row) for row in rows]


@app.get("/tasks")
def list_tasks(
    status: Literal["pending", "running", "done", "failed"] | None = None,
    limit: int = Query(50, ge=1, le=200),
    conn: sqlite3.Connection = Depends(get_conn),
):
    sql = """
        SELECT tasks.*, skills.name AS skill_name, skills.path AS skill_path
        FROM tasks LEFT JOIN skills ON skills.id = tasks.skill_id
    """
    args: list = []
    if status:
        sql += " WHERE tasks.status = ?"
        args.append(status)
    sql += " ORDER BY tasks.id DESC LIMIT ?"
    args.append(limit)
    return [dict(row) for row in conn.execute(sql, args).fetchall()]


@app.post("/tasks", status_code=201)
def create_task(body: TaskIn, conn: sqlite3.Connection = Depends(get_conn)):
    if body.skill_id is not None and conn.execute("SELECT 1 FROM skills WHERE id = ?", (body.skill_id,)).fetchone() is None:
        raise HTTPException(400, "skill not found")
    now = utcnow()
    cur = conn.execute(
        """
        INSERT INTO tasks (title, status, assignee, skill_id, payload, created_at, updated_at)
        VALUES (?, 'pending', NULL, ?, ?, ?, ?)
        """,
        (body.title, body.skill_id, dump_payload(body.payload), now, now),
    )
    return _task(conn, cur.lastrowid)


@app.post("/tasks/{task_id}/claim")
def claim_task(task_id: int, body: TaskClaimIn, conn: sqlite3.Connection = Depends(get_conn)):
    now = utcnow()
    conn.execute("BEGIN IMMEDIATE")
    row = conn.execute("SELECT status, assignee FROM tasks WHERE id = ?", (task_id,)).fetchone()
    if row is None:
        conn.rollback()
        raise HTTPException(404, "task not found")
    if row["status"] == "running" and row["assignee"] == body.assignee:
        conn.rollback()
        return _task(conn, task_id)
    cur = conn.execute(
        """
        UPDATE tasks SET status = 'running', assignee = ?, updated_at = ?
        WHERE id = ? AND status = 'pending'
        """,
        (body.assignee, now, task_id),
    )
    if cur.rowcount != 1:
        holder = conn.execute("SELECT assignee, status FROM tasks WHERE id = ?", (task_id,)).fetchone()
        conn.rollback()
        raise HTTPException(409, f"task is {holder['status']} (assignee={holder['assignee']})")
    conn.commit()
    return _task(conn, task_id)


@app.post("/tasks/{task_id}/status")
def update_task_status(task_id: int, body: TaskStatusIn, conn: sqlite3.Connection = Depends(get_conn)):
    current = conn.execute("SELECT assignee FROM tasks WHERE id = ?", (task_id,)).fetchone()
    if current is None:
        raise HTTPException(404, "task not found")
    assignee = body.assignee if body.assignee is not None else current["assignee"]
    if body.status == "running" and not assignee:
        raise HTTPException(400, "assignee required to mark running")
    if body.status == "pending":
        assignee = None
    conn.execute(
        "UPDATE tasks SET status = ?, assignee = ?, updated_at = ? WHERE id = ?",
        (body.status, assignee, utcnow(), task_id),
    )
    return _task(conn, task_id)


@app.get("/test-results")
def list_results(
    limit: int = Query(50, ge=1, le=200),
    conn: sqlite3.Connection = Depends(get_conn),
):
    rows = conn.execute(
        """
        SELECT test_results.*, skills.name AS skill_name, tasks.title AS task_title
        FROM test_results
        LEFT JOIN skills ON skills.id = test_results.skill_id
        LEFT JOIN tasks ON tasks.id = test_results.task_id
        ORDER BY test_results.id DESC
        LIMIT ?
        """,
        (limit,),
    ).fetchall()
    return [dict(row) for row in rows]


@app.post("/test-results", status_code=201)
def create_result(body: ResultIn, conn: sqlite3.Connection = Depends(get_conn)):
    if body.task_id is not None and conn.execute("SELECT 1 FROM tasks WHERE id = ?", (body.task_id,)).fetchone() is None:
        raise HTTPException(400, "task not found")
    if body.skill_id is not None and conn.execute("SELECT 1 FROM skills WHERE id = ?", (body.skill_id,)).fetchone() is None:
        raise HTTPException(400, "skill not found")
    now = utcnow()
    cur = conn.execute(
        """
        INSERT INTO test_results (agent_name, task_id, skill_id, status, summary, log_text, created_at)
        VALUES (?, ?, ?, ?, ?, ?, ?)
        """,
        (body.agent_name, body.task_id, body.skill_id, body.status, body.summary, body.log_text, now),
    )
    row = conn.execute("SELECT * FROM test_results WHERE id = ?", (cur.lastrowid,)).fetchone()
    return dict(row)


@app.get("/messages")
def list_messages(
    limit: int = Query(50, ge=1, le=200),
    conn: sqlite3.Connection = Depends(get_conn),
):
    rows = conn.execute(
        """
        SELECT id, from_agent, to_agent, body, created_at
        FROM messages WHERE kind = 'message'
        ORDER BY id DESC LIMIT ?
        """,
        (limit,),
    ).fetchall()
    return [dict(row) for row in rows]


@app.post("/messages", status_code=201)
def create_message(body: MessageIn, conn: sqlite3.Connection = Depends(get_conn)):
    now = utcnow()
    to_agent = body.to_agent or None
    cur = conn.execute(
        """
        INSERT INTO messages (kind, from_agent, to_agent, body, resource_name, status, created_at, updated_at)
        VALUES ('message', ?, ?, ?, NULL, 'sent', ?, ?)
        """,
        (body.from_agent, to_agent, body.body, now, now),
    )
    row = conn.execute(
        "SELECT id, from_agent, to_agent, body, created_at FROM messages WHERE id = ?",
        (cur.lastrowid,),
    ).fetchone()
    return dict(row)


@app.get("/claims")
def list_claims(
    status: Literal["held", "released"] | None = None,
    resource: str | None = None,
    limit: int = Query(50, ge=1, le=200),
    conn: sqlite3.Connection = Depends(get_conn),
):
    sql = "SELECT * FROM messages WHERE kind = 'claim'"
    args: list = []
    if status:
        sql += " AND status = ?"
        args.append(status)
    if resource:
        sql += " AND resource_name = ?"
        args.append(resource)
    sql += " ORDER BY id DESC LIMIT ?"
    args.append(limit)
    return [_claim_view(row) for row in conn.execute(sql, args).fetchall()]


@app.post("/claims")
def create_claim(body: ClaimIn, conn: sqlite3.Connection = Depends(get_conn)):
    now = utcnow()
    conn.execute("BEGIN IMMEDIATE")
    held = conn.execute(
        """
        SELECT * FROM messages
        WHERE kind = 'claim' AND status = 'held' AND resource_name = ?
        """,
        (body.resource,),
    ).fetchone()
    if held is not None:
        conn.rollback()
        if held["from_agent"] == body.owner:
            return _claim_view(held)
        raise HTTPException(409, f"resource held by {held['from_agent']}")
    try:
        cur = conn.execute(
            """
            INSERT INTO messages (kind, from_agent, to_agent, body, resource_name, status, created_at, updated_at)
            VALUES ('claim', ?, NULL, ?, ?, 'held', ?, ?)
            """,
            (body.owner, body.note, body.resource, now, now),
        )
        conn.commit()
    except sqlite3.IntegrityError:
        conn.rollback()
        raise HTTPException(409, "resource held")
    row = conn.execute("SELECT * FROM messages WHERE id = ?", (cur.lastrowid,)).fetchone()
    return UTF8JSONResponse(_claim_view(row), status_code=201)


@app.post("/claims/release")
def release_claim(body: ReleaseIn, conn: sqlite3.Connection = Depends(get_conn)):
    now = utcnow()
    conn.execute("BEGIN IMMEDIATE")
    cur = conn.execute(
        """
        UPDATE messages SET status = 'released', updated_at = ?
        WHERE kind = 'claim' AND status = 'held' AND resource_name = ? AND from_agent = ?
        """,
        (now, body.resource, body.owner),
    )
    if cur.rowcount != 1:
        conn.rollback()
        raise HTTPException(404, "no held claim for this owner and resource")
    conn.commit()
    row = conn.execute(
        """
        SELECT * FROM messages
        WHERE kind = 'claim' AND resource_name = ? AND from_agent = ?
        ORDER BY id DESC LIMIT 1
        """,
        (body.resource, body.owner),
    ).fetchone()
    return _claim_view(row)


def _counts(conn: sqlite3.Connection, sql: str, keys: tuple[str, ...]) -> dict[str, int]:
    found = {row["k"]: row["n"] for row in conn.execute(sql).fetchall()}
    return {key: int(found.get(key, 0)) for key in keys}


@app.get("/api/status")
def api_status(conn: sqlite3.Connection = Depends(get_conn)):
    tasks = _counts(
        conn,
        "SELECT status AS k, COUNT(*) AS n FROM tasks GROUP BY status",
        ("pending", "running", "done", "failed"),
    )
    results = _counts(
        conn,
        "SELECT status AS k, COUNT(*) AS n FROM test_results GROUP BY status",
        ("pass", "fail"),
    )
    held = conn.execute(
        "SELECT COUNT(*) AS n FROM messages WHERE kind = 'claim' AND status = 'held'"
    ).fetchone()["n"]
    return {"tasks": tasks, "results": results, "claims_held": held}
