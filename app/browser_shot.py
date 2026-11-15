"""通过本机 Chrome 调试协议抓一张当前页面的 JPEG。只连工作台自己的端口。"""

from __future__ import annotations

import base64

from app.browser_proc import FORBIDDEN_PORT
from app.cdp import CdpError, call


class ScreenshotError(Exception):
    """抓屏失败。调用方转成 HTTP 错误即可。"""


def capture_cdp_screenshot(port: int) -> bytes:
    """连到该调试端口上的第一个普通页面，返回 JPEG 字节。"""
    port = int(port or 0)
    if port <= 0 or port == FORBIDDEN_PORT:
        raise ScreenshotError("该端口不能抓屏")
    try:
        result = call(port, "Page.captureScreenshot", {"format": "jpeg", "quality": 55, "fromSurface": True})
    except CdpError as exc:
        # 个别版本不认 fromSurface，再试一次普通抓取
        if "fromSurface" in str(exc) or "unrecognized" in str(exc).lower():
            try:
                result = call(port, "Page.captureScreenshot", {"format": "jpeg", "quality": 55})
            except CdpError as exc2:
                raise ScreenshotError(str(exc2)) from exc2
        else:
            raise ScreenshotError(str(exc)) from exc
    raw_b64 = result.get("data")
    if not raw_b64:
        raise ScreenshotError("截图为空")
    try:
        data = base64.b64decode(raw_b64)
    except Exception as exc:
        raise ScreenshotError("截图解码失败") from exc
    if not data:
        raise ScreenshotError("截图为空")
    return data
