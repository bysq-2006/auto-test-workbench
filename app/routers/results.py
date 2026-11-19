"""子代理回写结果：测试通过/失败，或普通记录。

归属规则：挂了 task_id 就从那条任务抄 round_id；没挂 task_id 就必须自己带。
两条都带且对不上，说明调用方搞错了轮次，直接 400，不要替它猜。
"""

import sqlite3

from fastapi import APIRouter, Depends, HTTPException, Query

from app.db import utcnow
from app.deps import get_conn
from app.round_scope import require_open_round, round_filter
from app.schemas import ResultIn, ResultRecordedIn
from app.skill_files import resolve_skill, skill_fields

router = APIRouter()

_SELECT = """
    SELECT tr.*, t.title AS task_title, r.name AS round_name
    FROM test_results tr
    LEFT JOIN tasks t ON t.id = tr.task_id
    LEFT JOIN rounds r ON r.id = tr.round_id
"""


def _result_out(row) -> dict:
    data = dict(row)
    data["recorded"] = bool(data.get("recorded"))
    data.update(skill_fields(data.get("skill_path")))
    data.setdefault("task_title", None)
    return data


def _search_clause(q: str | None, kind: str | None, recorded: bool | None, round: str | None) -> tuple[str, list]:
    """可按类型、是否已记录、轮次筛；关键字在代理名、类型、状态、摘要、路径、日志和任务标题里做包含匹配。"""
    where: list[str] = []
    params: list = []
    if kind and kind.strip():
        where.append("tr.kind = ?")
        params.append(kind.strip())
    if recorded is not None:
        where.append("tr.recorded = ?")
        params.append(1 if recorded else 0)
    fragment, fragment_args = round_filter(round, "tr.round_id")
    if fragment:
        where.append(fragment)
        params.extend(fragment_args)
    if q and q.strip():
        key = f"%{q.strip()}%"
        where.append(
            "(tr.agent_name LIKE ? OR tr.kind LIKE ? OR IFNULL(tr.status, '') LIKE ?"
            " OR IFNULL(tr.summary, '') LIKE ? OR IFNULL(tr.skill_path, '') LIKE ?"
            " OR IFNULL(tr.log_text, '') LIKE ?"
            " OR IFNULL(t.title, '') LIKE ?)"
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
    round: str | None = Query(None),
    limit: int = Query(10, ge=1, le=200),
    page: int = Query(1, ge=1),
    conn: sqlite3.Connection = Depends(get_conn),
):
    where, params = _search_clause(q, kind, recorded, round)
    clause = "WHERE 1=1" + where
    total = conn.execute(
        f"SELECT COUNT(*) AS n FROM test_results tr LEFT JOIN tasks t ON t.id = tr.task_id {clause}",
        params,
    ).fetchone()["n"]
    offset = (page - 1) * limit
    rows = conn.execute(
        f"""
        {_SELECT}
        {clause}
        ORDER BY tr.id DESC
        LIMIT ? OFFSET ?
        """,
        (*params, limit, offset),
    ).fetchall()
    return {
        "items": [_result_out(row) for row in rows],
        "total": total,
        "page": page,
        "limit": limit,
    }


@router.post("/results", status_code=201)
def create_result(body: ResultIn, conn: sqlite3.Connection = Depends(get_conn)):
    round_id = body.round_id
    if body.task_id is not None:
        task = conn.execute("SELECT round_id FROM tasks WHERE id = ?", (body.task_id,)).fetchone()
        if task is None:
            raise HTTPException(400, "task not found")
        task_round = task["round_id"]
        if task_round is None:
            raise HTTPException(400, "这条任务没有归属轮次，先给任务补上 round_id")
        # 结果跟着任务走，调用方另指一轮就是搞错了
        if round_id is not None and int(round_id) != int(task_round):
            raise HTTPException(400, f"round_id 和任务不一致：任务 #{body.task_id} 在轮次 #{task_round}")
        round_id = task_round
    require_open_round(conn, round_id)

    skill_path = None
    if body.skill:
        skill = resolve_skill(body.skill)
        if skill is None:
            raise HTTPException(400, "skill not found")
        skill_path = skill["path"]
    now = utcnow()
    cur = conn.execute(
        """
        INSERT INTO test_results (agent_name, kind, task_id, skill_path, status, summary, log_text, round_id, created_at)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            body.agent_name,
            body.kind,
            body.task_id,
            skill_path,
            body.status,
            body.summary,
            body.log_text,
            round_id,
            now,
        ),
    )
    row = conn.execute(f"{_SELECT} WHERE tr.id = ?", (cur.lastrowid,)).fetchone()
    return _result_out(row)


@router.post("/results/{result_id}/recorded")
def set_recorded(result_id: int, body: ResultRecordedIn, conn: sqlite3.Connection = Depends(get_conn)):
    """主 AI 把这条结果标记为已记录或改回未记录。轮次关了也能改，这是审稿动作不是测数据。"""
    cur = conn.execute(
        "UPDATE test_results SET recorded = ? WHERE id = ?",
        (1 if body.recorded else 0, result_id),
    )
    if cur.rowcount != 1:
        raise HTTPException(404, "result not found")
    row = conn.execute(f"{_SELECT} WHERE tr.id = ?", (result_id,)).fetchone()
    return _result_out(row)


@router.delete("/results/{result_id}", status_code=204)
def delete_result(result_id: int, conn: sqlite3.Connection = Depends(get_conn)):
    """删掉一条结果。只删自己，不影响它绑定的任务。"""
    cur = conn.execute("DELETE FROM test_results WHERE id = ?", (result_id,))
    if cur.rowcount != 1:
        raise HTTPException(404, "result not found")
