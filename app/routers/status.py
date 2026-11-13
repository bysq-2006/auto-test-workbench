"""仪表盘用的汇总数字。"""

import sqlite3

from fastapi import APIRouter, Depends

from app.deps import get_conn

router = APIRouter()


def _counts(conn: sqlite3.Connection, sql: str, keys: tuple[str, ...]) -> dict[str, int]:
    found = {row["k"]: row["n"] for row in conn.execute(sql).fetchall()}
    return {key: int(found.get(key, 0)) for key in keys}


@router.get("/api/status")
def api_status(conn: sqlite3.Connection = Depends(get_conn)):
    tasks = _counts(
        conn,
        "SELECT status AS k, COUNT(*) AS n FROM tasks GROUP BY status",
        ("pending", "running", "done", "failed"),
    )
    # 只统计真正的测试结果；提案（note）的 status 是空的，不算通过或失败
    results = _counts(
        conn,
        "SELECT status AS k, COUNT(*) AS n FROM test_results WHERE kind = 'test' GROUP BY status",
        ("pass", "fail"),
    )
    # 提案单独一组：total 是全部，pending 是还没被主 AI 处理（recorded=0）的待审数
    notes = conn.execute(
        """
        SELECT COUNT(*) AS total,
               SUM(CASE WHEN recorded = 0 THEN 1 ELSE 0 END) AS pending
        FROM test_results WHERE kind = 'note'
        """
    ).fetchone()
    return {
        "tasks": tasks,
        "results": results,
        "notes": {
            "total": int(notes["total"] or 0),
            "pending": int(notes["pending"] or 0),
        },
    }
