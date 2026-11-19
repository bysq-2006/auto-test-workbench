"""仪表盘用的汇总数字。任务、结果、提案跟着轮次走；浏览器是全局资源，不分轮次。"""

import sqlite3

from fastapi import APIRouter, Depends, Query

from app.deps import get_conn
from app.round_scope import round_filter

router = APIRouter()


def _counts(conn: sqlite3.Connection, sql: str, keys: tuple[str, ...], args: list) -> dict[str, int]:
    found = {row["k"]: row["n"] for row in conn.execute(sql, args).fetchall()}
    return {key: int(found.get(key, 0)) for key in keys}


@router.get("/api/status")
def api_status(round: str | None = Query(None), conn: sqlite3.Connection = Depends(get_conn)):
    """round 不传就不限轮次；传编号只看这一轮；传 none 看未归类。"""
    fragment, args = round_filter(round)
    extra = (" AND " + fragment) if fragment else ""

    tasks = _counts(
        conn,
        f"SELECT status AS k, COUNT(*) AS n FROM tasks WHERE 1=1{extra} GROUP BY status",
        ("pending", "running", "done", "failed"),
        args,
    )
    # 只统计真正的测试结果；提案（note）的 status 是空的，不算通过或失败
    results = _counts(
        conn,
        f"SELECT status AS k, COUNT(*) AS n FROM test_results WHERE kind = 'test'{extra} GROUP BY status",
        ("pass", "fail"),
        args,
    )
    # 提案单独一组：total 是全部，pending 是还没被主 AI 处理（recorded=0）的待审数
    notes = conn.execute(
        f"""
        SELECT COUNT(*) AS total,
               SUM(CASE WHEN recorded = 0 THEN 1 ELSE 0 END) AS pending
        FROM test_results WHERE kind = 'note'{extra}
        """,
        args,
    ).fetchone()
    # 浏览器资源：空闲、被占用、已关闭各多少台。技能同理，都不跟轮次走
    browsers = _counts(
        conn,
        "SELECT status AS k, COUNT(*) AS n FROM browsers GROUP BY status",
        ("idle", "occupied", "closed"),
        [],
    )
    return {
        "tasks": tasks,
        "results": results,
        "notes": {
            "total": int(notes["total"] or 0),
            "pending": int(notes["pending"] or 0),
        },
        "browsers": browsers,
    }
