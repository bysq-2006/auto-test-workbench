"""轮次作用域：查询参数的 round 解析、写入时的 round_id 校验、轮次名清洗。

约定：轮次编号由主 AI 显式传给接口，服务端不做任何推断——没有「当前轮」这种隐式状态。
"""

import sqlite3

from fastapi import HTTPException

UNASSIGNED = "none"
ALL = "all"

# 轮次名要当 runs/ 下的目录名用，这几个字符在 Windows 上建不了目录
_BAD_NAME_CHARS = set('\\/:*?"<>|')
NAME_LIMIT = 40


def round_filter(value: str | None, column: str = "round_id") -> tuple[str, list]:
    """GET 的 round 参数 → (SQL 片段, 参数)。

    不传或传 all 表示不限轮次；none 表示查未归类（round_id IS NULL）；其余必须是轮次编号。
    """
    if value is None or not value.strip():
        return "", []
    text = value.strip().lower()
    if text == ALL:
        return "", []
    if text == UNASSIGNED:
        return f"{column} IS NULL", []
    try:
        return f"{column} = ?", [int(text)]
    except ValueError as exc:
        raise HTTPException(400, "round 只能是轮次编号、none 或 all") from exc


def get_round(conn: sqlite3.Connection, round_id: int) -> dict | None:
    row = conn.execute("SELECT * FROM rounds WHERE id = ?", (round_id,)).fetchone()
    return dict(row) if row else None


def require_open_round(conn: sqlite3.Connection, round_id: int | None, *, field: str = "round_id") -> dict:
    """写入前必须过这一关：没带、不存在、已关闭都不许写。"""
    if round_id is None:
        raise HTTPException(400, f"{field} 必填，服务端不猜轮次")
    data = get_round(conn, round_id)
    if data is None:
        raise HTTPException(400, f"轮次 #{round_id} 不存在")
    if data["status"] != "open":
        raise HTTPException(409, f"轮次 #{round_id}「{data['name']}」已关闭，只能查看")
    return data


def assert_round_open(conn: sqlite3.Connection, round_id: int | None) -> None:
    """已有数据（任务）所在轮次必须还开着，否则认领、改状态都要拦。"""
    if round_id is None:
        return
    data = get_round(conn, round_id)
    if data is None:
        raise HTTPException(409, f"轮次 #{round_id} 不存在")
    if data["status"] != "open":
        raise HTTPException(409, f"轮次 #{round_id}「{data['name']}」已关闭，只能查看")


def clean_round_name(raw: str | None) -> str:
    name = " ".join((raw or "").split())
    if not name:
        raise HTTPException(400, "轮次名不能为空")
    if len(name) > NAME_LIMIT:
        raise HTTPException(400, f"轮次名最多 {NAME_LIMIT} 个字")
    if any(ch in _BAD_NAME_CHARS or ord(ch) < 32 for ch in name):
        raise HTTPException(400, '轮次名不能含 \\ / : * ? " < > | 或控制字符')
    if name.endswith("."):
        raise HTTPException(400, "轮次名不能以点结尾")
    return name
