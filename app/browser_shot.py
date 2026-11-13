"""通过本机 Chrome 调试协议抓一张当前页面的 JPEG。只连工作台自己的端口。"""

from __future__ import annotations

import base64
import json
import os
import socket
import struct
from urllib.parse import urlparse
from urllib.request import Request, urlopen

from app.browser_proc import FORBIDDEN_PORT

# 单张截图上限，避免异常超大帧把接口拖死
MAX_FRAME = 8_000_000


class ScreenshotError(Exception):
    """抓屏失败。调用方转成 HTTP 错误即可。"""


def capture_cdp_screenshot(port: int) -> bytes:
    """连到该调试端口上的第一个普通页面，返回 JPEG 字节。"""
    port = int(port or 0)
    if port <= 0 or port == FORBIDDEN_PORT:
        raise ScreenshotError("该端口不能抓屏")
    ws_url = _page_ws_url(port)
    raw_b64 = _cdp_capture(ws_url)
    try:
        data = base64.b64decode(raw_b64)
    except Exception as exc:
        raise ScreenshotError("截图解码失败") from exc
    if not data:
        raise ScreenshotError("截图为空")
    return data


def _page_ws_url(port: int) -> str:
    url = f"http://127.0.0.1:{port}/json/list"
    try:
        with urlopen(Request(url, method="GET"), timeout=2) as resp:
            targets = json.loads(resp.read().decode("utf-8"))
    except Exception as exc:
        raise ScreenshotError(f"无法连接调试端口：{exc}") from exc
    if not isinstance(targets, list):
        raise ScreenshotError("调试端口返回异常")
    pages = [
        item
        for item in targets
        if item.get("type") == "page" and item.get("webSocketDebuggerUrl")
    ]
    if not pages:
        raise ScreenshotError("没有可抓取的页面")
    return pages[0]["webSocketDebuggerUrl"]


def _cdp_capture(ws_url: str) -> str:
    sock = None
    try:
        sock, leftover = _ws_handshake(ws_url)
        ws = _Ws(sock, leftover)
        payload = {
            "id": 1,
            "method": "Page.captureScreenshot",
            "params": {"format": "jpeg", "quality": 55, "fromSurface": True},
        }
        ws.send_text(json.dumps(payload))
        # 调试协议可能先推事件，一直读到 id=1 的结果
        while True:
            raw, opcode = ws.recv_message()
            if opcode != 0x1:
                continue
            try:
                msg = json.loads(raw.decode("utf-8"))
            except ValueError:
                continue
            if msg.get("id") not in (1, 2):
                continue
            if "error" in msg:
                err = (msg.get("error") or {}).get("message") or "截图失败"
                # 个别版本不认 fromSurface，再试一次普通抓取
                if msg.get("id") == 1 and ("fromSurface" in err or "unrecognized" in err.lower()):
                    ws.send_text(json.dumps({
                        "id": 2,
                        "method": "Page.captureScreenshot",
                        "params": {"format": "jpeg", "quality": 55},
                    }))
                    continue
                raise ScreenshotError(err)
            data = (msg.get("result") or {}).get("data")
            if not data:
                raise ScreenshotError("截图为空")
            return data
    finally:
        if sock is not None:
            try:
                sock.close()
            except OSError:
                pass


def _ws_handshake(ws_url: str, timeout: float = 3.0):
    parsed = urlparse(ws_url)
    host = parsed.hostname or "127.0.0.1"
    port = parsed.port or (443 if parsed.scheme == "wss" else 80)
    if host not in ("127.0.0.1", "localhost", "::1"):
        raise ScreenshotError("只允许连接本机调试端口")
    if port == FORBIDDEN_PORT:
        raise ScreenshotError("禁止连接 9229")
    path = parsed.path or "/"
    if parsed.query:
        path = f"{path}?{parsed.query}"
    sock = socket.create_connection((host, port), timeout=timeout)
    sock.settimeout(timeout)
    key = base64.b64encode(os.urandom(16)).decode("ascii")
    header = (
        f"GET {path} HTTP/1.1\r\n"
        f"Host: {host}:{port}\r\n"
        "Upgrade: websocket\r\n"
        "Connection: Upgrade\r\n"
        f"Sec-WebSocket-Key: {key}\r\n"
        "Sec-WebSocket-Version: 13\r\n"
        "\r\n"
    )
    sock.sendall(header.encode("ascii"))
    buf = b""
    while b"\r\n\r\n" not in buf:
        chunk = sock.recv(4096)
        if not chunk:
            sock.close()
            raise ScreenshotError("WebSocket 握手失败")
        buf += chunk
        if len(buf) > 65536:
            sock.close()
            raise ScreenshotError("WebSocket 握手过长")
    head, leftover = buf.split(b"\r\n\r\n", 1)
    status = head.split(b"\r\n", 1)[0].decode("ascii", "replace")
    if "101" not in status:
        sock.close()
        raise ScreenshotError(f"WebSocket 握手被拒绝：{status}")
    return sock, leftover


class _Ws:
    def __init__(self, sock: socket.socket, leftover: bytes = b""):
        self.sock = sock
        self.buf = leftover

    def _read_exact(self, n: int) -> bytes:
        while len(self.buf) < n:
            chunk = self.sock.recv(max(n - len(self.buf), 4096))
            if not chunk:
                raise ScreenshotError("连接中断")
            self.buf += chunk
        data, self.buf = self.buf[:n], self.buf[n:]
        return data

    def send_text(self, text: str) -> None:
        payload = text.encode("utf-8")
        header = bytearray([0x81])
        n = len(payload)
        if n < 126:
            header.append(0x80 | n)
        elif n < 65536:
            header.append(0x80 | 126)
            header.extend(struct.pack("!H", n))
        else:
            header.append(0x80 | 127)
            header.extend(struct.pack("!Q", n))
        mask = os.urandom(4)
        header.extend(mask)
        masked = bytes(b ^ mask[i % 4] for i, b in enumerate(payload))
        self.sock.sendall(header + masked)

    def recv_message(self) -> tuple[bytes, int]:
        collected = bytearray()
        opcode0 = None
        while True:
            b1, b2 = self._read_exact(2)
            fin = b1 & 0x80
            opcode = b1 & 0x0F
            masked = b2 & 0x80
            length = b2 & 0x7F
            if length == 126:
                length = struct.unpack("!H", self._read_exact(2))[0]
            elif length == 127:
                length = struct.unpack("!Q", self._read_exact(8))[0]
            if length > MAX_FRAME:
                raise ScreenshotError("截图过大")
            mask = self._read_exact(4) if masked else None
            payload = self._read_exact(length)
            if mask:
                payload = bytes(b ^ mask[i % 4] for i, b in enumerate(payload))
            if opcode == 0x8:
                raise ScreenshotError("连接已关闭")
            if opcode == 0x9:
                self._send_ctrl(0xA, payload)
                continue
            if opcode == 0xA:
                continue
            if opcode in (0x1, 0x2):
                opcode0 = opcode
                collected.extend(payload)
                if fin:
                    return bytes(collected), opcode0
                continue
            if opcode == 0x0 and opcode0 is not None:
                collected.extend(payload)
                if fin:
                    return bytes(collected), opcode0
                continue
            raise ScreenshotError("收到无法处理的数据帧")

    def _send_ctrl(self, opcode: int, payload: bytes) -> None:
        header = bytearray([0x80 | opcode, 0x80 | len(payload)])
        mask = os.urandom(4)
        header.extend(mask)
        masked = bytes(b ^ mask[i % 4] for i, b in enumerate(payload))
        self.sock.sendall(header + masked)
