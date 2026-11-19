"""轮次：一轮就是一次测试委托。任务、结果、消息挂在轮次下；技能和浏览器不分轮次。"""

import sqlite3

from fastapi import APIRouter, Depends, HTTPException

from app.db import RUNS_DIR, utcnow
from app.deps import get_conn
from app.round_scope import clean_round_name
from app.schemas import RoundCloseIn, RoundIn

router = APIRouter()

_COUNT_SQL = """
    SELECT
      (SELECT COUNT(*) FROM tasks WHERE round_id = ?) AS tasks,
      (SELECT COUNT(*) FROM test_results WHERE round_id = ?) AS results,
      (SELECT COUNT(*) FROM messages WHERE round_id = ?) AS messages
"""


def _counts(conn: sqlite3.Connection, round_id: int) -> dict[str, int]:
    row = conn.execute(_COUNT_SQL, (round_id, round_id, round_id)).fetchone()
    return {key: int(row[key] or 0) for key in ("tasks", "results", "messages")}


def round_out(conn: sqlite3.Connection, row) -> dict:
    data = dict(row)
    data.update(_counts(conn, data["id"]))
    # 关闭前要拦「还有活没干完」，所以顺带算一份
    data["alive_tasks"] = int(
        conn.execute(
            "SELECT COUNT(*) AS n FROM tasks WHERE round_id = ? AND status IN ('pending', 'running')",
            (data["id"],),
        ).fetchone()["n"]
    )
    return data


def _round_row(conn: sqlite3.Connection, round_id: int):
    row = conn.execute("SELECT * FROM rounds WHERE id = ?", (round_id,)).fetchone()
    if row is None:
        raise HTTPException(404, "round not found")
    return row


@router.get("/rounds")
def list_rounds(conn: sqlite3.Connection = Depends(get_conn)):
    """所有轮次，新的在前；另外报一份「未归类」条数，前端没有就不显示这一项。"""
    rows = conn.execute("SELECT * FROM rounds ORDER BY id DESC").fetchall()
    loose = conn.execute(
        """
        SELECT
          (SELECT COUNT(*) FROM tasks WHERE round_id IS NULL) AS tasks,
          (SELECT COUNT(*) FROM test_results WHERE round_id IS NULL) AS results,
          (SELECT COUNT(*) FROM messages WHERE round_id IS NULL) AS messages
        """
    ).fetchone()
    return {
        "items": [round_out(conn, row) for row in rows],
        "unassigned": {key: int(loose[key] or 0) for key in ("tasks", "results", "messages")},
    }


@router.post("/rounds", status_code=201)
def create_round(body: RoundIn, conn: sqlite3.Connection = Depends(get_conn)):
    """开一轮，顺手把 runs/<编号>-<名字>/ 建好。目录名不交给调用方拼，免得各写各的。"""
    name = clean_round_name(body.name)
    now = utcnow()
    conn.execute("BEGIN IMMEDIATE")
    try:
        cur = conn.execute(
            "INSERT INTO rounds (name, status, note, created_at) VALUES (?, 'open', ?, ?)",
            (name, (body.note or "").strip(), now),
        )
        round_id = cur.lastrowid
        target = RUNS_DIR / f"{round_id}-{name}"
        target.mkdir(parents=True, exist_ok=True)
        conn.execute("UPDATE rounds SET dir = ? WHERE id = ?", (str(target), round_id))
        conn.commit()
    except OSError as exc:
        conn.rollback()
        raise HTTPException(500, f"runs/ 下建不了目录：{exc}") from exc
    return round_out(conn, _round_row(conn, round_id))


@router.post("/rounds/{round_id}/close")
def close_round(round_id: int, body: RoundCloseIn, conn: sqlite3.Connection = Depends(get_conn)):
    """关轮后只能看：新建任务、回写结果、发消息都会被拒。"""
    row = _round_row(conn, round_id)
    if row["status"] == "closed":
        raise HTTPException(400, "这一轮已经关过了")
    note = body.note.strip()
    if not note:
        raise HTTPException(400, "关闭时要写一句本轮结论（note）")
    alive = int(
        conn.execute(
            "SELECT COUNT(*) AS n FROM tasks WHERE round_id = ? AND status IN ('pending', 'running')",
            (round_id,),
        ).fetchone()["n"]
    )
    if alive and not body.force:
        raise HTTPException(409, f"还有 {alive} 条任务没跑完，确认要关就带 force=true")
    conn.execute(
        "UPDATE rounds SET status = 'closed', note = ?, closed_at = ? WHERE id = ?",
        (note, utcnow(), round_id),
    )
    return round_out(conn, _round_row(conn, round_id))


@router.post("/rounds/{round_id}/reopen")
def reopen_round(round_id: int, conn: sqlite3.Connection = Depends(get_conn)):
    """关错了再启用回来：状态回到 open，关闭时间清掉。

    结论（note）留着，下次关闭会被新写的覆盖。目录、任务、结果、消息都不动。
    """
    row = _round_row(conn, round_id)
    if row["status"] == "open":
        raise HTTPException(400, "这一轮还在进行中，不用启用")
    conn.execute(
        "UPDATE rounds SET status = 'open', closed_at = NULL WHERE id = ?", (round_id,)
    )
    return round_out(conn, _round_row(conn, round_id))


@router.delete("/rounds/{round_id}")
def delete_round(round_id: int, conn: sqlite3.Connection = Depends(get_conn)):
    """只删空轮：建错了才用这个。有数据的轮只能关，不能删——报告里引用的编号会悬空。"""
    data = round_out(conn, _round_row(conn, round_id))
    used = data["tasks"] + data["results"] + data["messages"]
    if used:
        raise HTTPException(
            409,
            f"这一轮下面还有 {data['tasks']} 条任务、{data['results']} 条结果、"
            f"{data['messages']} 条消息，只能关闭，不能删除",
        )
    conn.execute("DELETE FROM rounds WHERE id = ?", (round_id,))
    return {"id": round_id, "deleted": True, "dir": data["dir"]}
