"""到达某个位置：真实点击左侧菜单，逐级点到目标页。

不走 router.push、不拼 hash——那样绕过前端自己的权限校验和页面初始化，
看着到了，数据没加载、菜单选中态也不对。这里全用鼠标事件，和手点等价。

快在哪：
- 一次调用只握一次手（Session 复用），不是一条命令连一次。
- 定位靠一次 JS 取回全部菜单项、坐标、层级，不逐个 querySelector。
- 等下一级用轮询，不 sleep 固定值；已经在目标页直接返回 0 点击。

这套菜单分两类，判定不一样：
- 一级（左侧图标列）和带子项的分组：点了只切组、只展开，**地址不变**。
- 叶子（分组下面的具体页面）：点了才真跳，地址会变。
所以 path 必须写到叶子；最后一段落在分组上会直接报错并列出可选页面，
不做「自动展开全部菜单再猜」——那会把菜单撑开、坐标错位，越猜越乱。
"""

from __future__ import annotations

import re
import time

from app.cdp import CdpError, Session

POLL = 0.06  # 轮询间隔，秒
DEFAULT_TIMEOUT = 4.0  # 整条路径的总预算，秒

# 取左侧导航区里所有可见的菜单项。不假设层级容器，只按位置和 class 过滤，
# 换皮肤或改嵌套都不会失效。level 按横向位置分：左边一条是 1，展开的列表是 2。
COLLECT_JS = r"""
(() => {
  const seen = new Set();
  const items = [];
  const limit = innerWidth * 0.35;   // 只认左侧那一条，右边内容区里的 el-menu 不算
  for (const el of document.querySelectorAll('.el-menu-item, .el-sub-menu__title')) {
    if (seen.has(el)) continue;
    seen.add(el);
    if (el.closest('.el-header')) continue;
    const r = el.getBoundingClientRect();
    if (r.width < 8 || r.height < 8) continue;
    if (r.left > limit) continue;
    if (r.bottom < 0 || r.top > innerHeight) continue;
    const text = (el.innerText || '').trim().replace(/\s+/g, ' ');
    if (!text || text.length > 20) continue;
    const cx = Math.round(r.left + r.width / 2);
    const cy = Math.round(r.top + r.height / 2);
    const top = document.elementFromPoint(cx, cy);   // 这个点最上层是不是它自己
    items.push({
      text: text,
      x: cx,
      y: cy,
      active: /(^|\s)is-active(\s|$)/.test(el.className.toString()),
      sub: el.classList.contains('el-sub-menu__title'),
      // 一级在左边窄条（中心约 40px），展开的列表整块从 80px 起、中心约 180px
      level: cx < 100 ? 1 : 2,
      hittable: !!(top && (el === top || el.contains(top))),
    });
  }
  const mask = document.querySelector('.el-loading-mask');
  return {
    url: location.href,
    loading: !!mask && mask.getBoundingClientRect().width > 0,
    items: items,
  };
})()
"""


def parse_path(raw) -> list[str]:
    """把 "殡仪管理/殡仪业务办理"、["殡仪管理", "殡仪业务办理"] 都拆成段。"""
    if isinstance(raw, (list, tuple)):
        segs = [str(x) for x in raw]
    else:
        segs = re.split(r"\s*(?:>>|>|/|→)\s*", str(raw or ""))
    return [seg.strip() for seg in segs if seg and seg.strip()]


def _collect(session: Session) -> dict:
    value = session.js(COLLECT_JS)
    if not isinstance(value, dict):
        raise CdpError("页面上取不到菜单结构")
    return value


def match(items: list[dict], seg: str) -> dict | None:
    """先找完全同名的，再找包含关系。同名优先，避免「殡仪管理」命中「殡仪管理2」。"""
    for item in items:
        if item["text"] == seg:
            return item
    for item in items:
        if seg in item["text"]:
            return item
    return None


def is_leaf(item: dict) -> bool:
    """叶子才算页面：分组标题和左侧一级都不算。"""
    return not item["sub"] and item["level"] > 1


def _click(session: Session, x: int, y: int) -> None:
    session.call("Input.dispatchMouseEvent", {"type": "mouseMoved", "x": x, "y": y, "buttons": 0})
    session.call(
        "Input.dispatchMouseEvent",
        {"type": "mousePressed", "x": x, "y": y, "button": "left", "clickCount": 1, "buttons": 1},
    )
    time.sleep(0.01)
    session.call(
        "Input.dispatchMouseEvent",
        {"type": "mouseReleased", "x": x, "y": y, "button": "left", "clickCount": 1, "buttons": 1},
    )


def _wait_next(session: Session, seg: str, deadline: float) -> dict:
    """等下一级菜单出现，并且停在能点的位置。

    点到分组后会展开动画，动画中子项的坐标一直在动。这里要求「已在 DOM 上」
    加「该点最上层就是它自己」加「连着两次坐标一样」三条同时成立，
    否则照着动画中间态去点，会点到相邻的另一个菜单。
    """
    state = _collect(session)
    started = time.monotonic()
    signature = None
    stable = 0
    last_spot = None
    while time.monotonic() < deadline:
        hit = match(state["items"], seg)
        if hit and hit.get("hittable"):
            spot = (hit["x"], hit["y"])
            if spot == last_spot:
                return state
            last_spot = spot
        else:
            last_spot = None
        sig = tuple(i["text"] for i in state["items"])
        if sig == signature:
            stable += 1
            if stable >= 5 and not state["loading"] and time.monotonic() - started > 0.25:
                return state
        else:
            stable = 0
            signature = sig
        time.sleep(POLL)
        try:
            state = _collect(session)
        except CdpError:
            continue  # 页面正在换，取不到就再看下一轮
    return state


def _settle(session: Session, before_url: str, deadline: float) -> dict:
    """等最后一下点击生效：地址一变就返回，没变化最多等 0.7 秒。"""
    soft_end = time.monotonic() + 0.7
    state = _collect(session)
    while time.monotonic() < deadline:
        moved = state["url"] != before_url
        if moved and not state["loading"]:
            return state
        if not moved and time.monotonic() >= soft_end:
            return state
        time.sleep(POLL)
        try:
            state = _collect(session)
        except CdpError:
            continue
    return state


def _aim(session: Session, seg: str, deadline: float) -> tuple[dict, dict | None]:
    """等目标变成「点得到」的状态，返回最新的页面状态和目标。"""
    state = _collect(session)
    hit = match(state["items"], seg)
    while (hit is None or not hit.get("hittable")) and time.monotonic() < deadline:
        time.sleep(POLL)
        try:
            state = _collect(session)
        except CdpError:
            continue
        hit = match(state["items"], seg)
    return state, hit


def navigate(port: int, path, timeout: float = DEFAULT_TIMEOUT) -> dict:
    """点到 path 指定的页面。返回 ok/ms/clicks/steps，失败时带原因和当时能看见的菜单。"""
    segs = parse_path(path)
    if not segs:
        return {"ok": False, "reason": "path 是空的", "ms": 0, "clicks": 0, "steps": [], "path": []}

    started = time.monotonic()
    deadline = started + timeout
    steps: list[dict] = []

    with Session(port) as session:
        state = _collect(session)

        # 已经是目标叶子且选中，不点，避免重复点击触发刷新
        current = match(state["items"], segs[-1])
        if current and is_leaf(current) and current["active"]:
            return _done(state, segs, steps, started, port, note="已经在该页面，未点击")

        for index, seg in enumerate(segs):
            hit = match(state["items"], seg)
            if hit is None:
                return _fail(
                    state, segs, steps, started, len(steps),
                    f"找不到「{seg}」，当前能看见的是 {[i['text'] for i in state['items']]}",
                )

            # 目标在 DOM 上但那个点被别的东西盖着（动画中、遮罩），等它自己浮上来
            if not hit.get("hittable"):
                state, hit = _aim(session, seg, min(deadline, time.monotonic() + 0.6))
                if hit is None or not hit.get("hittable"):
                    return _fail(state, segs, steps, started, len(steps),
                                 f"「{seg}」在页面上点不到，可能被遮挡或还在动画里")

            is_last = index == len(segs) - 1
            if is_last and not is_leaf(hit):
                # 落到一级或分组上：点了也不会换页，说清楚还得往下写一级
                _click(session, hit["x"], hit["y"])
                time.sleep(0.25)
                state = _collect(session)
                leaves = [i["text"] for i in state["items"] if is_leaf(i)]
                return {
                    "ok": False,
                    "reason": f"「{hit['text']}」是分组或一级菜单，到不了页面，后面还要再写一级",
                    "failed_at": hit["text"],
                    "visible": leaves or [i["text"] for i in state["items"]],
                    "url": state["url"],
                    "ms": _elapsed(started),
                    "clicks": 1,
                    "path": segs,
                    "steps": steps,
                }

            if is_last and hit["active"]:
                steps.append({"text": hit["text"], "ms": 0, "skipped": True})
                break

            url_before = state["url"]
            click_start = time.monotonic()
            _click(session, hit["x"], hit["y"])

            if is_last:
                state = _settle(session, url_before, min(deadline, time.monotonic() + 1.4))
            else:
                state = _wait_next(session, segs[index + 1], min(deadline, time.monotonic() + timeout))

            steps.append({
                "text": hit["text"],
                "ms": _elapsed(click_start),
                "url_changed": state["url"] != url_before,
                "sub": bool(hit["sub"]),
            })

            if not is_last and not match(state["items"], segs[index + 1]):
                return _fail(
                    state, segs, steps, started,
                    len([s for s in steps if not s.get("skipped")]),
                    f"点了「{hit['text']}」，但下一级「{segs[index + 1]}」没出现",
                )

        return _done(state, segs, steps, started, port)


def _fail(state: dict, segs: list[str], steps: list[dict], started: float, clicks: int, reason: str) -> dict:
    return {
        "ok": False,
        "reason": reason,
        "visible": [i["text"] for i in state["items"]],
        "url": state["url"],
        "ms": _elapsed(started),
        "clicks": clicks,
        "path": segs,
        "steps": steps,
    }


def _done(state: dict, segs: list[str], steps: list[dict], started: float, port: int, note: str = "") -> dict:
    target = segs[-1]
    hit = match(state["items"], target)
    clicked = [s for s in steps if not s.get("skipped")]
    moved = bool(clicked and clicked[-1].get("url_changed"))
    ok = bool(hit and is_leaf(hit) and hit["active"])

    out = {
        "ok": ok,
        "path": segs,
        "url": state["url"],
        "active": hit["text"] if hit else None,
        "ms": _elapsed(started),
        "clicks": len(clicked),
        "steps": steps,
        "port": port,
        "loading": state["loading"],
    }
    if note:
        out["note"] = note
    elif clicked and not moved:
        out["note"] = "菜单选中了但地址没变，确认一下这个菜单是不是同页内的切换"
    if not ok:
        out["reason"] = f"点完了但「{target}」不是选中的页面节点"
        out["visible"] = [i["text"] for i in state["items"]]
    return out


def _elapsed(started: float) -> int:
    return int((time.monotonic() - started) * 1000)
