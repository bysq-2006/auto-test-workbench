"""浏览器资源：列表、启动、占用/释放、关闭、抓屏。"""

import sqlite3
from typing import Literal

from fastapi import APIRouter, Body, Depends, HTTPException, Query
from fastapi.responses import Response

from app.browser_proc import (
    FORBIDDEN_PORT,
    BrowserLaunchError,
    cleanup_user_data_dir,
    port_bindable,
    spawn_browser_on_record,
    spawn_idle_browser,
    stop_owned_browser,
)
from app.browser_shot import ScreenshotError, capture_cdp_screenshot
from app.db import utcnow
from app.deps import get_conn
from app.schemas import BrowserCreateIn, BrowserStatusIn

router = APIRouter()


def _browser_out(row) -> dict:
    return dict(row)


def _browser(conn: sqlite3.Connection, browser_id: int) -> dict:
    row = conn.execute("SELECT * FROM browsers WHERE id = ?", (browser_id,)).fetchone()
    if row is None:
        raise HTTPException(404, "browser not found")
    return _browser_out(row)


def _try_cleanup(path: str | None) -> None:
    """清残留目录失败不该影响结果：状态已经落库了，别把请求变成 500。"""
    try:
        cleanup_user_data_dir(path)
    except (Exception, SystemExit):
        pass


@router.get("/browsers")
def list_browsers(
    status: Literal["idle", "occupied", "closed"] | None = None,
    q: str | None = Query(None),
    limit: int = Query(10, ge=1, le=200),
    page: int = Query(1, ge=1),
    conn: sqlite3.Connection = Depends(get_conn),
):
    """查看浏览器资源。可按状态筛，关键字匹配端口或使用者。"""
    where: list[str] = []
    params: list = []
    if status:
        where.append("status = ?")
        params.append(status)
    if q and q.strip():
        key = f"%{q.strip()}%"
        where.append("(CAST(port AS TEXT) LIKE ? OR IFNULL(agent_name, '') LIKE ?)")
        params.extend([key, key])
    clause = " AND ".join(where) if where else "1=1"
    total = conn.execute(f"SELECT COUNT(*) AS n FROM browsers WHERE {clause}", params).fetchone()["n"]
    offset = (page - 1) * limit
    rows = conn.execute(
        f"""
        SELECT * FROM browsers
        WHERE {clause}
        ORDER BY id DESC
        LIMIT ? OFFSET ?
        """,
        (*params, limit, offset),
    ).fetchall()
    return {
        "items": [_browser_out(row) for row in rows],
        "total": total,
        "page": page,
        "limit": limit,
    }


@router.post("/browsers", status_code=201)
def create_browser(
    body: BrowserCreateIn = Body(default_factory=BrowserCreateIn),
    conn: sqlite3.Connection = Depends(get_conn),
):
    """服务端选空闲端口并启动浏览器，写入 idle 记录。不要传 port。"""
    extra = body.model_extra or {}
    if "port" in extra:
        raise HTTPException(400, "端口由服务端分配，不能自己传")
    try:
        return spawn_idle_browser(conn)
    except BrowserLaunchError as exc:
        raise HTTPException(500, str(exc)) from exc


@router.get("/browsers/{browser_id}/screenshot")
def browser_screenshot(
    browser_id: int,
    conn: sqlite3.Connection = Depends(get_conn),
):
    """抓取该实例当前页面的 JPEG。只连库里未关闭记录的端口，不碰 9229。"""
    row = conn.execute("SELECT * FROM browsers WHERE id = ?", (browser_id,)).fetchone()
    if row is None:
        raise HTTPException(404, "browser not found")
    if row["status"] == "closed":
        raise HTTPException(400, "已关闭的浏览器没有画面")
    port = int(row["port"] or 0)
    if port <= 0 or port == FORBIDDEN_PORT:
        raise HTTPException(400, "该端口不能抓屏")
    try:
        data = capture_cdp_screenshot(port)
    except ScreenshotError as exc:
        raise HTTPException(502, str(exc)) from exc
    return Response(
        content=data,
        media_type="image/jpeg",
        headers={"Cache-Control": "no-store"},
    )


@router.post("/browsers/{browser_id}/power-on")
def power_on_browser(
    browser_id: int,
    conn: sqlite3.Connection = Depends(get_conn),
):
    """给一条已关闭的记录开机：端口和 user_data_dir 都沿用原记录。

    等于把这台「电脑」重新通电，不是新建一台。端口已被别的进程占掉就返回 409，
    不要自己换端口——换了就是另一台机器，记录会对不上。
    """
    row = conn.execute("SELECT * FROM browsers WHERE id = ?", (browser_id,)).fetchone()
    if row is None:
        raise HTTPException(404, "browser not found")
    current = dict(row)
    if current["status"] != "closed":
        raise HTTPException(400, "这台还没关闭，不用开机")
    port = int(current["port"] or 0)
    if port <= 0 or port == FORBIDDEN_PORT:
        raise HTTPException(400, "该端口不能启动")
    if not port_bindable(port):
        raise HTTPException(409, f"端口 {port} 已被别的进程占用，无法开机")
    try:
        return spawn_browser_on_record(conn, current)
    except BrowserLaunchError as exc:
        raise HTTPException(500, str(exc)) from exc


@router.delete("/browsers/{browser_id}")
def delete_browser(
    browser_id: int,
    conn: sqlite3.Connection = Depends(get_conn),
):
    """删掉一条已关闭的资源记录。只删库里的行，不碰进程。

    未关闭的记录不许删：真进程可能还在跑，删了记录就等于把端口和登录态弄丢。
    先 POST /browsers/{id}/status 置 closed，再删。
    """
    conn.execute("BEGIN IMMEDIATE")
    row = conn.execute("SELECT * FROM browsers WHERE id = ?", (browser_id,)).fetchone()
    if row is None:
        conn.rollback()
        raise HTTPException(404, "browser not found")
    current = dict(row)
    if current["status"] != "closed":
        conn.rollback()
        raise HTTPException(400, "只有已关闭的资源才能删除，请先关闭")
    conn.execute("DELETE FROM browsers WHERE id = ?", (browser_id,))
    conn.commit()
    _try_cleanup(current.get("user_data_dir"))
    return {"id": browser_id, "deleted": True}


@router.post("/browsers/{browser_id}/status")
def update_browser_status(
    browser_id: int,
    body: BrowserStatusIn,
    conn: sqlite3.Connection = Depends(get_conn),
):
    """idle 释放、occupied 占用、closed 结束本条进程。closed 是终态。"""
    now = utcnow()
    conn.execute("BEGIN IMMEDIATE")
    row = conn.execute("SELECT * FROM browsers WHERE id = ?", (browser_id,)).fetchone()
    if row is None:
        conn.rollback()
        raise HTTPException(404, "browser not found")
    current = dict(row)
    if current["status"] == "closed":
        conn.rollback()
        raise HTTPException(400, "已关闭的浏览器不能再改状态")

    if body.status == "occupied":
        agent_name = (body.agent_name or "").strip()
        if not agent_name:
            conn.rollback()
            raise HTTPException(400, "占用时必须带非空 agent_name")
        holder = (current.get("agent_name") or "").strip()
        if current["status"] == "occupied" and holder and holder != agent_name:
            conn.rollback()
            raise HTTPException(409, f"browser is occupied (agent_name={holder})")
        conn.execute(
            "UPDATE browsers SET status = 'occupied', agent_name = ?, updated_at = ? WHERE id = ?",
            (agent_name, now, browser_id),
        )
        conn.commit()
        return _browser(conn, browser_id)

    if body.status == "idle":
        conn.execute(
            "UPDATE browsers SET status = 'idle', agent_name = NULL, updated_at = ? WHERE id = ?",
            (now, browser_id),
        )
        conn.commit()
        return _browser(conn, browser_id)

    # closed：先确认是工作台自己的进程，再标终态。进程没了也照样关闭。
    note = stop_owned_browser(current.get("pid"), current.get("user_data_dir") or "", current.get("port") or 0)
    conn.execute(
        "UPDATE browsers SET status = 'closed', updated_at = ? WHERE id = ?",
        (now, browser_id),
    )
    conn.commit()
    _try_cleanup(current.get("user_data_dir"))
    data = _browser(conn, browser_id)
    if note:
        data["note"] = note
    return data
