"""工作台自己启动的 Chrome/Chromium：选端口、拉起进程、按 PID 结束。"""

from __future__ import annotations

import os
import shutil
import socket
import signal
import subprocess
import time
import uuid
from pathlib import Path

from app.db import ROOT, utcnow

# 用户自己的调试端口，工作台永远不分配、不探测、不连接、不结束
FORBIDDEN_PORT = 9229
PORT_START = 9330
PORT_SPAN = 2000

RUN_DIR = ROOT / "runs" / "browsers"


class BrowserLaunchError(Exception):
    """启动失败。调用方不要往库里写 idle 记录。"""


def find_browser_exe() -> Path | None:
    """优先本机 Google Chrome，其次 PATH、Edge、Playwright 自带 Chromium。"""
    candidates: list[Path] = []
    program_files = os.environ.get("PROGRAMFILES", r"C:\Program Files")
    program_files_x86 = os.environ.get("PROGRAMFILES(X86)", r"C:\Program Files (x86)")
    local_appdata = os.environ.get("LOCALAPPDATA", "")
    candidates.extend(
        [
            Path(program_files) / "Google" / "Chrome" / "Application" / "chrome.exe",
            Path(program_files_x86) / "Google" / "Chrome" / "Application" / "chrome.exe",
        ]
    )
    if local_appdata:
        candidates.append(Path(local_appdata) / "Google" / "Chrome" / "Application" / "chrome.exe")
    for path in candidates:
        if path.is_file():
            return path

    for name in ("chrome.exe", "chrome"):
        found = shutil.which(name)
        if found:
            return Path(found)

    for path in (
        Path(program_files) / "Microsoft" / "Edge" / "Application" / "msedge.exe",
        Path(program_files_x86) / "Microsoft" / "Edge" / "Application" / "msedge.exe",
    ):
        if path.is_file():
            return path
    edge = shutil.which("msedge.exe") or shutil.which("msedge")
    if edge:
        return Path(edge)

    return _playwright_chromium()


def _playwright_chromium() -> Path | None:
    roots: list[Path] = []
    local_appdata = os.environ.get("LOCALAPPDATA")
    if local_appdata:
        roots.append(Path(local_appdata) / "ms-playwright")
    roots.append(Path.home() / "AppData" / "Local" / "ms-playwright")
    seen: set[Path] = set()
    matches: list[Path] = []
    for root in roots:
        resolved = root.resolve() if root.exists() else root
        if resolved in seen:
            continue
        seen.add(resolved)
        if not root.is_dir():
            continue
        matches.extend(root.glob("chromium-*/chrome-win/chrome.exe"))
    if not matches:
        return None
    return sorted(matches, reverse=True)[0]


def port_bindable(port: int) -> bool:
    """本机能否绑上这个端口。不连接已有服务，更不要去碰 9229。"""
    if port == FORBIDDEN_PORT:
        return False
    sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    try:
        sock.bind(("127.0.0.1", port))
        return True
    except OSError:
        return False
    finally:
        sock.close()


def used_ports(conn) -> set[int]:
    rows = conn.execute("SELECT port FROM browsers WHERE status != 'closed'").fetchall()
    return {int(row["port"]) for row in rows}


def pick_free_port(conn) -> int:
    """从 9330 向上找：库里没有未关闭记录，且当前能 bind。"""
    taken = used_ports(conn)
    taken.add(FORBIDDEN_PORT)
    for port in range(PORT_START, PORT_START + PORT_SPAN):
        if port in taken:
            continue
        if port_bindable(port):
            return port
    raise BrowserLaunchError("找不到空闲的浏览器调试端口")


def prepare_user_data_dir(port: int) -> Path:
    """每个实例一个独立目录，绝对路径，不要用用户默认 Chrome 配置。"""
    RUN_DIR.mkdir(parents=True, exist_ok=True)
    path = (RUN_DIR / f"{port}-{uuid.uuid4().hex[:12]}").resolve()
    path.mkdir(parents=True, exist_ok=True)
    return path


def launch_browser(exe: Path, port: int, user_data_dir: Path) -> int:
    """用操作系统子进程拉起可见窗口，只记录 PID，不持有 Playwright 对象。"""
    if port == FORBIDDEN_PORT:
        raise BrowserLaunchError("禁止使用 9229")
    args = [
        str(exe),
        f"--remote-debugging-port={port}",
        f"--user-data-dir={user_data_dir}",
        "--no-first-run",
        "--no-default-browser-check",
        "--remote-allow-origins=*",
        "about:blank",
    ]
    kwargs: dict = {
        "stdout": subprocess.DEVNULL,
        "stderr": subprocess.DEVNULL,
        "stdin": subprocess.DEVNULL,
    }
    if os.name == "nt":
        # Windows 上重定向标准流时不能 close_fds=True。新进程组，结束时只杀记下的 PID。
        kwargs["close_fds"] = False
        kwargs["creationflags"] = subprocess.CREATE_NEW_PROCESS_GROUP
    else:
        kwargs["close_fds"] = True
        kwargs["start_new_session"] = True
    try:
        proc = subprocess.Popen(args, **kwargs)
    except OSError as exc:
        raise BrowserLaunchError(f"启动浏览器失败：{exc}") from exc
    time.sleep(0.4)
    if proc.poll() is not None:
        raise BrowserLaunchError(f"浏览器进程启动后立刻退出，退出码 {proc.returncode}")
    return int(proc.pid)


def spawn_idle_browser(conn) -> dict:
    """选端口、启动、写入 idle 记录。失败时不留可用记录，并清掉本次目录。"""
    exe = find_browser_exe()
    if exe is None:
        raise BrowserLaunchError("本机未找到 Chrome / Chromium，无法启动浏览器")

    conn.execute("BEGIN IMMEDIATE")
    port: int | None = None
    user_data_dir: Path | None = None
    pid: int | None = None
    try:
        port = pick_free_port(conn)
        user_data_dir = prepare_user_data_dir(port)
        pid = launch_browser(exe, port, user_data_dir)
        now = utcnow()
        cur = conn.execute(
            """
            INSERT INTO browsers (port, status, agent_name, pid, user_data_dir, created_at, updated_at)
            VALUES (?, 'idle', NULL, ?, ?, ?, ?)
            """,
            (port, pid, str(user_data_dir), now, now),
        )
        conn.commit()
        row = conn.execute("SELECT * FROM browsers WHERE id = ?", (cur.lastrowid,)).fetchone()
        return dict(row)
    except Exception:
        try:
            conn.rollback()
        except Exception:
            pass
        if pid:
            # 已经拉起但没入库：只结束刚才这个 PID，且命令行必须对得上本次目录
            stop_owned_browser(pid, str(user_data_dir) if user_data_dir else "", port or 0)
        if user_data_dir is not None:
            _rm_tree(user_data_dir)
        raise


def spawn_browser_on_record(conn, record: dict) -> dict:
    """按原记录重新开机：端口不变，user_data_dir 有就沿用，没了就照同一路径重建。"""
    exe = find_browser_exe()
    if exe is None:
        raise BrowserLaunchError("本机未找到 Chrome / Chromium，无法启动浏览器")

    port = int(record["port"])
    raw_dir = (record.get("user_data_dir") or "").strip()
    user_data_dir = Path(raw_dir).resolve() if raw_dir else prepare_user_data_dir(port)
    user_data_dir.mkdir(parents=True, exist_ok=True)

    conn.execute("BEGIN IMMEDIATE")
    pid: int | None = None
    try:
        pid = launch_browser(exe, port, user_data_dir)
        conn.execute(
            """
            UPDATE browsers
            SET status = 'idle', agent_name = NULL, pid = ?, user_data_dir = ?, updated_at = ?
            WHERE id = ?
            """,
            (pid, str(user_data_dir), utcnow(), record["id"]),
        )
        conn.commit()
        return dict(conn.execute("SELECT * FROM browsers WHERE id = ?", (record["id"],)).fetchone())
    except Exception:
        try:
            conn.rollback()
        except Exception:
            pass
        if pid:
            # 起来了但没入库：只结束刚才这个 PID，命令行对不上就不杀
            stop_owned_browser(pid, str(user_data_dir), port)
        raise


def pid_alive(pid: int | None) -> bool:
    if pid is None or int(pid) <= 0:
        return False
    try:
        os.kill(int(pid), 0)
        return True
    except OSError:
        return False
    except SystemError:
        return False


def process_cmdline(pid: int) -> str | None:
    """读该 PID 的命令行。读不到就当作无法确认，调用方不要杀。"""
    if os.name != "nt":
        proc_file = Path(f"/proc/{int(pid)}/cmdline")
        try:
            return proc_file.read_bytes().replace(b"\x00", b" ").decode("utf-8", "replace").strip()
        except OSError:
            return None
    flags = getattr(subprocess, "CREATE_NO_WINDOW", 0)
    filter_pid = int(pid)
    commands = [
        [
            "powershell",
            "-NoProfile",
            "-Command",
            f"(Get-CimInstance Win32_Process -Filter 'ProcessId={filter_pid}').CommandLine",
        ],
        [
            "wmic",
            "process",
            "where",
            f"ProcessId={filter_pid}",
            "get",
            "CommandLine",
            "/VALUE",
        ],
    ]
    for cmd in commands:
        try:
            completed = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                timeout=8,
                creationflags=flags,
            )
        except (OSError, subprocess.SubprocessError):
            continue
        if completed.returncode != 0:
            continue
        text = (completed.stdout or "").strip()
        if not text:
            continue
        if cmd[0] == "wmic":
            for line in text.splitlines():
                if line.lower().startswith("commandline="):
                    value = line.split("=", 1)[1].strip()
                    return value or None
            continue
        return text
    return None


def _dir_in_cmdline(user_data_dir: str, cmdline: str) -> bool:
    if not user_data_dir or not cmdline:
        return False
    want = os.path.normcase(os.path.abspath(user_data_dir))
    text = os.path.normcase(cmdline)
    alts = {want, want.replace("\\", "/"), want.replace("/", "\\")}
    return any(item in text for item in alts if item)


def stop_owned_browser(pid: int | None, user_data_dir: str, port: int) -> str:
    """只结束工作台记下的那个 PID。对不上命令行或碰上 9229 则不杀。"""
    if port == FORBIDDEN_PORT:
        return "端口是 9229，工作台不会结束该进程"
    if pid is None or int(pid) <= 0:
        return "没有记录 PID"
    pid = int(pid)
    if not pid_alive(pid):
        return "进程已经不在了"
    cmdline = process_cmdline(pid)
    if not cmdline:
        return "无法确认进程命令行，未结束该进程"
    if f"--remote-debugging-port={FORBIDDEN_PORT}" in cmdline.replace(" ", ""):
        return "命令行带有 9229，工作台不会结束该进程"
    if not _dir_in_cmdline(user_data_dir, cmdline):
        return "PID 已被其他进程复用，未结束该进程"
    _kill_pid(pid)
    return ""


def _kill_pid(pid: int) -> None:
    # 只用 /PID，禁止 /IM chrome.exe。/T 只跟这一棵子进程树。
    if os.name == "nt":
        flags = getattr(subprocess, "CREATE_NO_WINDOW", 0)
        try:
            subprocess.run(
                ["taskkill", "/PID", str(int(pid)), "/T", "/F"],
                capture_output=True,
                timeout=8,
                creationflags=flags,
            )
            return
        except (OSError, subprocess.SubprocessError):
            pass
    try:
        os.kill(int(pid), signal.SIGTERM)
    except OSError:
        pass


def _rm_tree(path: Path | str | None) -> None:
    if not path:
        return
    folder = Path(path)
    if not folder.exists():
        return
    shutil.rmtree(folder, ignore_errors=True)


def cleanup_user_data_dir(path: str | None) -> None:
    if not path:
        return
    time.sleep(0.2)
    _rm_tree(path)
