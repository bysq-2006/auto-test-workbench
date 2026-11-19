"""任务队列接口。给 agent 创建、认领和改状态，工作台列表也会展示。"""

import sqlite3
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, Query

from app.db import utcnow
from app.deps import dump_payload, get_conn
from app.round_scope import assert_round_open, require_open_round, round_filter
from app.schemas import TaskClaimIn, TaskIn, TaskStatusIn
from app.skill_files import resolve_skill, skill_fields

router = APIRouter()

# 带上轮次名，主 AI 建完任务后从任务响应里就能读到「本轮编号和名称」
_SELECT = "SELECT t.*, r.name AS round_name FROM tasks t LEFT JOIN rounds r ON r.id = t.round_id"


def _task_out(row) -> dict:
    data = dict(row)
    data.update(skill_fields(data.get("skill_path")))
    return data


def _task(conn: sqlite3.Connection, task_id: int) -> dict:
    row = conn.execute(f"{_SELECT} WHERE t.id = ?", (task_id,)).fetchone()
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
    round: str | None = Query(None),
    q: str | None = Query(None),
    limit: int = Query(10, ge=1, le=200),
    page: int = Query(1, ge=1),
    conn: sqlite3.Connection = Depends(get_conn),
):
    """round 不传就是不限轮次；传编号只看这一轮；传 none 看未归类。"""
    where: list[str] = []
    args: list = []
    if status:
        where.append("t.status = ?")
        args.append(status)
    fragment, fragment_args = round_filter(round, "t.round_id")
    if fragment:
        where.append(fragment)
        args.extend(fragment_args)
    if q and q.strip():
        key = f"%{q.strip()}%"
        where.append(
            "(t.title LIKE ? OR IFNULL(t.description, '') LIKE ? OR IFNULL(t.agent_name, '') LIKE ? OR IFNULL(t.skill_path, '') LIKE ?)"
        )
        args.extend([key, key, key, key])
    clause = ("WHERE " + " AND ".join(where)) if where else ""
    total = conn.execute(f"SELECT COUNT(*) AS n FROM tasks t {clause}", args).fetchone()["n"]
    offset = (page - 1) * limit
    rows = conn.execute(
        f"{_SELECT} {clause} ORDER BY t.id DESC LIMIT ? OFFSET ?",
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
    require_open_round(conn, body.round_id)
    now = utcnow()
    cur = conn.execute(
        """
        INSERT INTO tasks (title, description, status, agent_name, skill_path, payload, round_id, created_at, updated_at)
        VALUES (?, ?, 'pending', NULL, ?, ?, ?, ?, ?)
        """,
        (
            body.title,
            body.description or "",
            skill_path,
            dump_payload(body.payload),
            body.round_id,
            now,
            now,
        ),
    )
    return _task(conn, cur.lastrowid)


@router.post("/tasks/{task_id}/claim")
def claim_task(task_id: int, body: TaskClaimIn, conn: sqlite3.Connection = Depends(get_conn)):
    # BEGIN IMMEDIATE 先拿到写锁，避免两个 agent 同时把同一条 pending 认领走
    now = utcnow()
    conn.execute("BEGIN IMMEDIATE")
    row = conn.execute("SELECT status, agent_name, round_id FROM tasks WHERE id = ?", (task_id,)).fetchone()
    if row is None:
        conn.rollback()
        raise HTTPException(404, "task not found")
    # 轮次关了就别接活：接得住但结果写不进去，只会卡在 running
    try:
        assert_round_open(conn, row["round_id"])
    except HTTPException:
        conn.rollback()
        raise
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
    current = conn.execute("SELECT agent_name, round_id FROM tasks WHERE id = ?", (task_id,)).fetchone()
    if current is None:
        raise HTTPException(404, "task not found")
    assert_round_open(conn, current["round_id"])
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


@router.delete("/tasks/{task_id}", status_code=204)
def delete_task(task_id: int, conn: sqlite3.Connection = Depends(get_conn)):
    """删掉一条任务。挂在它下面的结果不会被删，task_id 自动置空（外键 ON DELETE SET NULL）。

    结果的 round_id 是独立存的，所以任务没了也还留在原来那一轮里。
    """
    cur = conn.execute("DELETE FROM tasks WHERE id = ?", (task_id,))
    if cur.rowcount != 1:
        raise HTTPException(404, "task not found")
