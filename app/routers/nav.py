"""导航接口：点菜单到指定位置。一次调用算一件事，不落库。"""

from __future__ import annotations

import sqlite3

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import JSONResponse
from pydantic import BaseModel

from app.cdp import CdpError, page_targets
from app.deps import get_conn
from app.nav import DEFAULT_TIMEOUT, navigate, parse_path

router = APIRouter()


class NavIn(BaseModel):
    """path 可以写 "殡仪管理/殡仪业务办理"，也可以传数组。"""

    path: str | list[str]
    port: int | None = None
    browser_id: int | None = None
    timeout: float | None = None


def _resolve_port(conn: sqlite3.Connection, body: NavIn) -> int:
    if body.port:
        return int(body.port)
    if body.browser_id is not None:
        row = conn.execute("SELECT id, port FROM browsers WHERE id = ?", (body.browser_id,)).fetchone()
        if row is None:
            raise HTTPException(404, f"没有 id={body.browser_id} 的浏览器")
        return int(row["port"])

    # 没指定就自己找一台还活着的：状态不是 closed，调试端口能连上
    alive: list[int] = []
    for row in conn.execute("SELECT port FROM browsers WHERE status != 'closed' ORDER BY id DESC"):
        port = int(row["port"])
        try:
            page_targets(port, timeout=0.4)
        except CdpError:
            continue
        alive.append(port)
    if not alive:
        raise HTTPException(409, "没有可用的浏览器，先在资源页启动一台")
    return alive[0]


@router.post("/navigate")
def navigate_to(body: NavIn, conn: sqlite3.Connection = Depends(get_conn)):
    """点左侧菜单到达目标位置。

    返回 ok、耗时 ms、点了几次。找不到某一级时 ok=false，并带回当时能看见的菜单。
    已经在目标页会直接返回，clicks=0。
    """
    segs = parse_path(body.path)
    if not segs:
        raise HTTPException(400, "path 不能为空")
    if len(segs) > 4:
        raise HTTPException(400, f"path 最多 4 级，收到 {len(segs)} 级")

    port = _resolve_port(conn, body)
    timeout = float(body.timeout or DEFAULT_TIMEOUT)
    try:
        result = navigate(port, segs, timeout=timeout)
    except CdpError as exc:
        raise HTTPException(502, f"连不上浏览器 {port}：{exc}") from exc

    if not result.get("ok"):
        # 失败也把完整结果带回去，调用方能看到是哪一级断的
        return JSONResponse(status_code=409, content=result)
    return result
