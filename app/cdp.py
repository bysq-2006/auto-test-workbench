"""最小可用的 Chrome 调试协议客户端：只要一条 WebSocket 调用，不引第三方库。

只连本机、只连工作台自己的端口，禁止 9229。
"""

from __future__ import annotations

import base64
import json
import os
import socket
import struct
from urllib.parse import urlparse
from urllib.request import Request, urlopen

from app.browser_proc import FORBIDDEN_PORT

# 单个消息上限，避免异常超大帧把请求拖死
MAX_FRAME = 8_000_000


class CdpError(Exception):
    """连不上调试端口，或该命令返回错误。"""


def page_targets(port: int, timeout: float = 2.0) -> list[dict]:
    """该端口上的目标列表（页面、worker 等）。"""
    port = int(port or 0)
    if port <= 0 or port == FORBIDDEN_PORT:
        raise CdpError("该端口不能连接")
    url = f"http://127.0.0.1:{port}/json/list"
    try:
        with urlopen(Request(url, method="GET"), timeout=timeout) as resp:
            targets = json.loads(resp.read().decode("utf-8"))
    except Exception as exc:
        raise CdpError(f"无法连接调试端口：{exc}") from exc
    if not isinstance(targets, list):
        raise CdpError("调试端口返回异常")
    return [item for item in targets if isinstance(item, dict)]


def page_ws_url(port: int, timeout: float = 2.0) -> str:
    """取该端口上第一个普通页面的 WebSocket 地址。"""
    pages = [
        item
        for item in page_targets(port, timeout)
        if item.get("type") == "page" and item.get("webSocketDebuggerUrl")
    ]
    if not pages:
        raise CdpError("没有可用的页面")
    return pages[0]["webSocketDebuggerUrl"]


class Session:
    """一条 WebSocket 连接上连发多条命令。

    握手一次约 10~20ms，点一次菜单要好几次命令，逐次重连会把耗时叠起来。
    用完 close()，或用 with。
    """

    def __init__(self, port: int, timeout: float = 5.0):
        self.timeout = timeout
        self.port = int(port or 0)
        self._id = 0
        ws_url = page_ws_url(self.port, timeout)
        self.sock, leftover = _ws_handshake(ws_url, timeout)
        self.sock.settimeout(timeout)
        self.ws = _Ws(self.sock, leftover)

    def call(self, method: str, params: dict | None = None) -> dict:
        self._id += 1
        mid = self._id
        self.ws.send_text(json.dumps({"id": mid, "method": method, "params": params or {}}))
        # 调试协议会先推事件，一直读到本次 id 的结果
        while True:
            raw, opcode = self.ws.recv_message()
            if opcode != 0x1:
                continue
            try:
                msg = json.loads(raw.decode("utf-8"))
            except ValueError:
                continue
            if msg.get("id") != mid:
                continue
            if "error" in msg:
                err = (msg.get("error") or {}).get("message") or f"{method} 失败"
                raise CdpError(err)
            return msg.get("result") or {}

    def js(self, expression: str):
        """执行一段 JS，返回它的值。页面里抛错时给回 CdpError。"""
        res = self.call("Runtime.evaluate", {"expression": expression, "returnByValue": True, "awaitPromise": True})
        detail = res.get("exceptionDetails")
        if detail:
            text = (detail.get("exception") or {}).get("description") or detail.get("text") or "页面脚本出错"
            raise CdpError(str(text).splitlines()[0][:200])
        return (res.get("result") or {}).get("value")

    def close(self) -> None:
        try:
            self.sock.close()
        except OSError:
            pass

    def __enter__(self) -> "Session":
        return self

    def __exit__(self, *_exc) -> None:
        self.close()


def call(port: int, method: str, params: dict | None = None, timeout: float = 5.0) -> dict:
    """发一条命令，用完就断开。要多条命令走 Session。"""
    with Session(port, timeout) as session:
        return session.call(method, params)


def _ws_handshake(ws_url: str, timeout: float = 3.0):
    parsed = urlparse(ws_url)
    host = parsed.hostname or "127.0.0.1"
    port = parsed.port or (443 if parsed.scheme == "wss" else 80)
    if host not in ("127.0.0.1", "localhost", "::1"):
        raise CdpError("只允许连接本机调试端口")
    if port == FORBIDDEN_PORT:
        raise CdpError("禁止连接 9229")
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
            raise CdpError("WebSocket 握手失败")
        buf += chunk
        if len(buf) > 65536:
            sock.close()
            raise CdpError("WebSocket 握手过长")
    head, leftover = buf.split(b"\r\n\r\n", 1)
    status = head.split(b"\r\n", 1)[0].decode("ascii", "replace")
    if "101" not in status:
        sock.close()
        raise CdpError(f"WebSocket 握手被拒绝：{status}")
    return sock, leftover


class _Ws:
    def __init__(self, sock: socket.socket, leftover: bytes = b""):
        self.sock = sock
        self.buf = leftover

    def _read_exact(self, n: int) -> bytes:
        while len(self.buf) < n:
            chunk = self.sock.recv(max(n - len(self.buf), 4096))
            if not chunk:
                raise CdpError("连接中断")
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
                raise CdpError("消息过大")
            mask = self._read_exact(4) if masked else None
            payload = self._read_exact(length)
            if mask:
                payload = bytes(b ^ mask[i % 4] for i, b in enumerate(payload))
            if opcode == 0x8:
                raise CdpError("连接已关闭")
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
            raise CdpError("收到无法处理的数据帧")

    def _send_ctrl(self, opcode: int, payload: bytes) -> None:
        header = bytearray([0x80 | opcode, 0x80 | len(payload)])
        mask = os.urandom(4)
        header.extend(mask)
        masked = bytes(b ^ mask[i % 4] for i, b in enumerate(payload))
        self.sock.sendall(header + masked)
