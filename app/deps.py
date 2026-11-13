"""请求级公共依赖。"""

import json
from typing import Any

from fastapi.responses import JSONResponse

from app.db import locked_connect


class UTF8JSONResponse(JSONResponse):
    """保证中文直接以 UTF-8 返回，不被转成 unicode 转义。"""

    def render(self, content: Any) -> bytes:
        return json.dumps(content, ensure_ascii=False).encode("utf-8")


def get_conn():
    # FastAPI 会把同步接口丢到线程池，进/出可能不在同一线程。
    # locked_connect() 内部已加锁，并且关闭了 SQLite 的同线程检查。
    with locked_connect() as conn:
        yield conn


def dump_payload(value: Any) -> str | None:
    """任务附加数据统一存成文本，已是字符串就原样写入。"""
    if value is None:
        return None
    if isinstance(value, str):
        return value
    return json.dumps(value, ensure_ascii=False)
