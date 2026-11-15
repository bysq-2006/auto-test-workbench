"""子代理回写结果：测试通过/失败，或普通记录。"""

import sqlite3

from fastapi import APIRouter, Depends, HTTPException, Query

from app.db import utcnow
from app.deps import get_conn
from app.schemas import ResultIn, ResultRecordedIn
from app.skill_files import resolve_skill, skill_fields

router = APIRouter()


def _result_out(conn: sqlite3.Connection, row) -> dict:
    data = dict(row)
    data["recorded"] = bool(data.get("recorded"))
    data.update(skill_fields(data.get("skill_path")))
    if data.get("task_id") is not None:
        task = conn.execute("SELECT title FROM tasks WHERE id = ?", (data["task_id"],)).fetchone()
        data["task_title"] = task["title"] if task else None
    else:
        data["task_title"] = None
    return data


def _search_clause(q: str | None, kind: str | None, recorded: bool | None) -> tuple[str, list]:
    """可按类型、是否已记录筛；关键字在代理名、类型、状态、摘要、路径、日志和任务标题里做包含匹配。"""
    where = []
    params: list = []
    if kind and kind.strip():
        where.append("kind = ?")
        params.append(kind.strip())
    if recorded is not None:
        where.append("recorded = ?")
        params.append(1 if recorded else 0)
    if q and q.strip():
        key = f"%{q.strip()}%"
        where.append(
            "(agent_name LIKE ? OR kind LIKE ? OR IFNULL(status, '') LIKE ?"
            " OR IFNULL(summary, '') LIKE ? OR IFNULL(skill_path, '') LIKE ?"
            " OR IFNULL(log_text, '') LIKE ?"
            " OR EXISTS (SELECT 1 FROM tasks WHERE tasks.id = test_results.task_id AND tasks.title LIKE ?))"
        )
        params.extend([key, key, key, key, key, key, key])
    if not where:
        return "", []
    return " AND " + " AND ".join(where), params


@router.get("/results")
def list_results(
    q: str | None = Query(None),
    kind: str | None = Query(None),
    recorded: bool | None = Query(None),
    limit: int = Query(10, ge=1, le=200),
    page: int = Query(1, ge=1),
    conn: sqlite3.Connection = Depends(get_conn),
):
    where, params = _search_clause(q, kind, recorded)
    clause = "WHERE 1=1" + where
    total = conn.execute(f"SELECT COUNT(*) AS n FROM test_results {clause}", params).fetchone()["n"]
    offset = (page - 1) * limit
    rows = conn.execute(
        f"""
        SELECT * FROM test_results
        {clause}
        ORDER BY id DESC
        LIMIT ? OFFSET ?
        """,
        (*params, limit, offset),
    ).fetchall()
    return {
        "items": [_result_out(conn, row) for row in rows],
        "total": total,
        "page": page,
        "limit": limit,
    }


@router.post("/results", status_code=201)
def create_result(body: ResultIn, conn: sqlite3.Connection = Depends(get_conn)):
    if body.task_id is not None and conn.execute(
        "SELECT 1 FROM tasks WHERE id = ?", (body.task_id,)
    ).fetchone() is None:
        raise HTTPException(400, "task not found")
    skill_path = None
    if body.skill:
        skill = resolve_skill(body.skill)
        if skill is None:
            raise HTTPException(400, "skill not found")
        skill_path = skill["path"]
    now = utcnow()
    cur = conn.execute(
        """
        INSERT INTO test_results (agent_name, kind, task_id, skill_path, status, summary, log_text, created_at)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (body.agent_name, body.kind, body.task_id, skill_path, body.status, body.summary, body.log_text, now),
    )
    row = conn.execute("SELECT * FROM test_results WHERE id = ?", (cur.lastrowid,)).fetchone()
    return _result_out(conn, row)


@router.post("/results/{result_id}/recorded")
def set_recorded(result_id: int, body: ResultRecordedIn, conn: sqlite3.Connection = Depends(get_conn)):
    """主 AI 把这条结果标记为已记录或改回未记录。"""
    cur = conn.execute(
        "UPDATE test_results SET recorded = ? WHERE id = ?",
        (1 if body.recorded else 0, result_id),
    )
    if cur.rowcount != 1:
        raise HTTPException(404, "result not found")
    row = conn.execute("SELECT * FROM test_results WHERE id = ?", (result_id,)).fetchone()
    return _result_out(conn, row)


@router.delete("/results/{result_id}", status_code=204)
def delete_result(result_id: int, conn: sqlite3.Connection = Depends(get_conn)):
    """删掉一条结果。只删自己，不影响它绑定的任务。"""
    cur = conn.execute("DELETE FROM test_results WHERE id = ?", (result_id,))
    if cur.rowcount != 1:
        raise HTTPException(404, "result not found")

