"""任务队列接口。给 agent 创建、认领和改状态，工作台列表也会展示。"""

import sqlite3
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, Query

from app.db import utcnow
from app.deps import dump_payload, get_conn
from app.schemas import TaskClaimIn, TaskIn, TaskStatusIn
from app.skill_files import resolve_skill, skill_fields

router = APIRouter()


def _task_out(row) -> dict:
    data = dict(row)
    data.update(skill_fields(data.get("skill_path")))
    return data


def _task(conn: sqlite3.Connection, task_id: int) -> dict:
    row = conn.execute("SELECT * FROM tasks WHERE id = ?", (task_id,)).fetchone()
    if row is None:
        raise HTTPException(404, "task not found")
    return _task_out(row)


def _skill_path_or_400(ref: str | None) -> str | None:
    if not ref:
        return None
    skill = resolve_skill(ref)
    if skill is None:
        raise HTTPException(400, "skill not found")
    return skill["path"]


@router.get("/tasks")
def list_tasks(
    status: Literal["pending", "running", "done", "failed"] | None = None,
    q: str | None = Query(None),
    limit: int = Query(10, ge=1, le=200),
    page: int = Query(1, ge=1),
    conn: sqlite3.Connection = Depends(get_conn),
):
    where: list[str] = []
    args: list = []
    if status:
        where.append("status = ?")
        args.append(status)
    if q and q.strip():
        key = f"%{q.strip()}%"
        where.append(
            "(title LIKE ? OR IFNULL(description, '') LIKE ? OR IFNULL(agent_name, '') LIKE ? OR IFNULL(skill_path, '') LIKE ?)"
        )
        args.extend([key, key, key, key])
    clause = ("WHERE " + " AND ".join(where)) if where else ""
    total = conn.execute(f"SELECT COUNT(*) AS n FROM tasks {clause}", args).fetchone()["n"]
    offset = (page - 1) * limit
    rows = conn.execute(
        f"SELECT * FROM tasks {clause} ORDER BY id DESC LIMIT ? OFFSET ?",
        (*args, limit, offset),
    ).fetchall()
    return {
        "items": [_task_out(row) for row in rows],
        "total": total,
        "page": page,
        "limit": limit,
    }


@router.post("/tasks", status_code=201)
def create_task(body: TaskIn, conn: sqlite3.Connection = Depends(get_conn)):
    skill_path = _skill_path_or_400(body.skill)
    now = utcnow()
    cur = conn.execute(
        """
        INSERT INTO tasks (title, description, status, agent_name, skill_path, payload, created_at, updated_at)
        VALUES (?, ?, 'pending', NULL, ?, ?, ?, ?)
        """,
        (body.title, body.description or "", skill_path, dump_payload(body.payload), now, now),
    )
    return _task(conn, cur.lastrowid)


@router.post("/tasks/{task_id}/claim")
def claim_task(task_id: int, body: TaskClaimIn, conn: sqlite3.Connection = Depends(get_conn)):
    # BEGIN IMMEDIATE 先拿到写锁，避免两个 agent 同时把同一条 pending 认领走
    now = utcnow()
    conn.execute("BEGIN IMMEDIATE")
    row = conn.execute("SELECT status, agent_name FROM tasks WHERE id = ?", (task_id,)).fetchone()
    if row is None:
        conn.rollback()
        raise HTTPException(404, "task not found")
    if row["status"] == "running" and row["agent_name"] == body.agent_name:
        conn.rollback()
        return _task(conn, task_id)
    cur = conn.execute(
        """
        UPDATE tasks SET status = 'running', agent_name = ?, updated_at = ?
        WHERE id = ? AND status = 'pending'
        """,
        (body.agent_name, now, task_id),
    )
    if cur.rowcount != 1:
        holder = conn.execute("SELECT agent_name, status FROM tasks WHERE id = ?", (task_id,)).fetchone()
        conn.rollback()
        raise HTTPException(409, f"task is {holder['status']} (agent_name={holder['agent_name']})")
    conn.commit()
    return _task(conn, task_id)


@router.post("/tasks/{task_id}/status")
def update_task_status(task_id: int, body: TaskStatusIn, conn: sqlite3.Connection = Depends(get_conn)):
    current = conn.execute("SELECT agent_name FROM tasks WHERE id = ?", (task_id,)).fetchone()
    if current is None:
        raise HTTPException(404, "task not found")
    agent_name = body.agent_name if body.agent_name is not None else current["agent_name"]
    if body.status == "running" and not agent_name:
        raise HTTPException(400, "agent_name required to mark running")
    if body.status == "pending":
        agent_name = None
    conn.execute(
        "UPDATE tasks SET status = ?, agent_name = ?, updated_at = ? WHERE id = ?",
        (body.status, agent_name, utcnow(), task_id),
    )
    return _task(conn, task_id)
