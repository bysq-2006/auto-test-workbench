"""公共聊天厅：发送和接收消息。"""

import sqlite3
from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, Depends, HTTPException, Query

from app.db import utcnow
from app.deps import get_conn
from app.schemas import MessageIn

router = APIRouter()

BEIJING = timezone(timedelta(hours=8))


def _parse_time(value: str, *, end: bool = False) -> str:
    """把查询参数里的时间统一成 UTC ISO，方便和 created_at 做字符串比较。"""
    text = value.strip()
    if text.endswith("Z"):
        text = text[:-1] + "+00:00"
    try:
        if len(text) == 10 and text[4] == "-" and text[7] == "-":
            dt = datetime.strptime(text, "%Y-%m-%d").replace(tzinfo=BEIJING)
            if end:
                dt = dt.replace(hour=23, minute=59, second=59)
        else:
            dt = datetime.fromisoformat(text)
            if dt.tzinfo is None:
                dt = dt.replace(tzinfo=BEIJING)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=f"时间格式不对：{value}") from exc
    return dt.astimezone(timezone.utc).isoformat(timespec="seconds")


def _message_out(row) -> dict:
    data = dict(row)
    return {
        "id": data["id"],
        "name": data["from_agent"] or "",
        "body": data["body"],
        "created_at": data["created_at"],
    }


@router.get("/messages")
def list_messages(
    name: str | None = Query(None),
    q: str | None = Query(None),
    since: str | None = Query(None),
    until: str | None = Query(None),
    limit: int = Query(10, ge=1, le=200),
    page: int = Query(1, ge=1),
    conn: sqlite3.Connection = Depends(get_conn),
):
    """拉取公共聊天厅消息。什么筛选都不传时，默认第 1 页、每页 10 条。q 是标题和正文的包含搜索。"""
    where: list[str] = []
    params: list = []
    if name and name.strip():
        where.append("from_agent = ?")
        params.append(name.strip())
    if q and q.strip():
        key = f"%{q.strip()}%"
        where.append("(IFNULL(from_agent, '') LIKE ? OR IFNULL(body, '') LIKE ?)")
        params.extend([key, key])
    if since and since.strip():
        where.append("created_at >= ?")
        params.append(_parse_time(since, end=False))
    if until and until.strip():
        where.append("created_at <= ?")
        params.append(_parse_time(until, end=True))
    clause = " AND ".join(where) if where else "1=1"
    total = conn.execute(
        f"SELECT COUNT(*) AS n FROM messages WHERE {clause}",
        params,
    ).fetchone()["n"]
    offset = (page - 1) * limit
    rows = conn.execute(
        f"""
        SELECT id, from_agent, body, created_at
        FROM messages WHERE {clause}
        ORDER BY id DESC LIMIT ? OFFSET ?
        """,
        (*params, limit, offset),
    ).fetchall()
    return {
        "items": [_message_out(row) for row in rows],
        "total": total,
        "page": page,
        "limit": limit,
    }


@router.post("/messages", status_code=201)
def create_message(body: MessageIn, conn: sqlite3.Connection = Depends(get_conn)):
    """往公共聊天厅发一条。名字可不传。"""
    now = utcnow()
    name = (body.name or "").strip()
    cur = conn.execute(
        """
        INSERT INTO messages (from_agent, body, created_at)
        VALUES (?, ?, ?)
        """,
        (name, body.body, now),
    )
    row = conn.execute(
        "SELECT id, from_agent, body, created_at FROM messages WHERE id = ?",
        (cur.lastrowid,),
    ).fetchone()
    return _message_out(row)
