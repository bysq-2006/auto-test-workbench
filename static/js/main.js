/** 入口：挂上路由、分页和各页自己的筛选搜索，启动后每 5 秒刷新一次数据。 */

import { delJSON, load, postJSON, refreshRounds, storeRound } from "./api.js";
import { docsCrumb, docsReady, loadArticles, renderDocs } from "./docs.js";
import { onDeleteClick, onPagerClick } from "./list.js";
import { renderDashboard } from "./pages/dashboard.js";
import {
  onBrowserNameCommit,
  onBrowsersAction,
  onShotIntervalChange,
  renderBrowsers,
  restoreBrowserShots,
  snapshotBrowserShots,
  startBrowserShots,
  stopBrowserShots,
} from "./pages/browsers.js";
import { renderMessages } from "./pages/messages.js";
import { renderResults } from "./pages/results.js";
import { renderSkills } from "./pages/skills.js";
import { renderTasks } from "./pages/tasks.js";
import { PAGES, pageId, setRoundParam } from "./router.js";
import { state } from "./state.js";
import { $, esc } from "./util.js";

const views = {
  dashboard: renderDashboard,
  skills: renderSkills,
  tasks: renderTasks,
  results: renderResults,
  browsers: renderBrowsers,
  messages: renderMessages,
  docs: renderDocs,
};

/** 重绘时若焦点在搜索框或筛选项上，把光标位置还原回去，避免 5 秒轮询把输入打乱。 */
function setPageHtml(html) {
  const page = $("page");
  const active = document.activeElement;
  const restore = (active && page.contains(active) && active.id) ? {
    id: active.id,
    start: active.selectionStart,
    end: active.selectionEnd,
    value: active.matches("[data-browser-name]") ? active.value : null,
  } : null;
  page.innerHTML = html;
  if (!restore) return;
  const el = document.getElementById(restore.id);
  if (!el) return;
  if (restore.value != null) el.value = restore.value;
  el.focus();
  if (typeof restore.start === "number" && typeof el.setSelectionRange === "function") {
    try { el.setSelectionRange(restore.start, restore.end); } catch (err) { /* 下拉框没有选区 */ }
  }
}

/** 未归类一共多少条：任务、结果、消息加起来。 */
function looseCount() {
  const u = state.roundsUnassigned || {};
  return Number(u.tasks || 0) + Number(u.results || 0) + Number(u.messages || 0);
}

function roundMetaText() {
  const r = state.round;
  if (!r) return "还没有轮次";
  if (r.status === "none") return "未归类 · " + looseCount() + " 条";
  return "#" + r.id + " · " + (r.status === "closed" ? "已归档" : "进行中");
}

function roundItemHtml({ value, name, meta, status, active, more, moreOpen }) {
  const dot = "round-dot" + (status === "closed" ? " is-closed" : status === "none" ? " is-empty" : "");
  const moreBtn = more == null ? "" : `
    <button type="button" class="round-more" data-more="${esc(more)}" aria-haspopup="menu"
      aria-expanded="${moreOpen ? "true" : "false"}" title="这一轮的操作">⋯</button>`;
  return `<div class="round-row">
    <button type="button" class="round-item${active ? " is-active" : ""}"
      data-round="${esc(value)}" role="option" aria-selected="${active ? "true" : "false"}">
      <span class="${dot}"></span>
      <span class="round-body">
        <span class="rname" title="${esc(name)}">${esc(name)}</span>
        <span class="rmeta">${esc(meta)}</span>
      </span>
    </button>${moreBtn}
  </div>`;
}

/** 下拉内容。搜索只在前端过滤，不重新请求。 */
function paintRoundList() {
  const box = $("round-list");
  if (!box) return;
  const key = state.roundQuery.trim().toLowerCase();
  const hit = (text) => !key || String(text).toLowerCase().includes(key);
  const activeId = state.round ? state.round.id : null;
  const rows = state.rounds
    .filter((r) => hit(r.name) || String(r.id) === key)
    .map((r) => roundItemHtml({
      value: r.id,
      name: r.name,
      meta: "#" + r.id + " · " + (r.status === "closed" ? "已归档" : "进行中")
        + (r.tasks ? " · " + r.tasks + " 项" : ""),
      status: r.status,
      active: r.id === activeId,
      more: r.id,
      moreOpen: state.roundOps === r.id,
    }));
  const loose = looseCount();
  if (loose && (hit("未归类") || !key)) {
    rows.push('<div class="round-sep"></div>');
    rows.push(roundItemHtml({
      value: "none",
      name: "未归类",
      meta: loose + " 条",
      status: "none",
      active: !!state.round && state.round.status === "none",
      more: null,
      moreOpen: false,
    }));
  }
  box.innerHTML = rows.length
    ? rows.join("")
    : '<div class="round-empty">' + (state.rounds.length ? "没有匹配的轮次" : "还没有轮次") + "</div>";
}

/** 收掉行内的小弹窗。 */
function closeRoundOps() {
  state.roundOps = null;
  const pop = $("round-ops");
  if (pop) {
    pop.hidden = true;
    pop.innerHTML = "";
  }
  document.querySelectorAll('.round-more[aria-expanded="true"]').forEach((btn) => {
    btn.setAttribute("aria-expanded", "false");
  });
}

/** 每行右侧「…」的小弹窗：启用 / 关闭 / 删除，都在这一轮上生效。 */
function toggleRoundOps(id, anchor) {
  if (state.roundOps === id) {
    closeRoundOps();
    return;
  }
  const r = state.rounds.find((item) => item.id === id);
  if (!r) return;
  closeRoundOps();
  state.roundOps = id;
  anchor.setAttribute("aria-expanded", "true");

  const used = roundDataCount(r);
  const canEnable = r.status === "closed";
  const canClose = r.status === "open";
  const pop = $("round-ops");
  pop.innerHTML = `
    <button type="button" role="menuitem" data-op="enable" data-op-id="${r.id}"
      ${canEnable ? "" : "disabled"} title="${canEnable ? "改回进行中" : "这一轮还在进行中"}">启用</button>
    <button type="button" role="menuitem" data-op="close" data-op-id="${r.id}"
      ${canClose ? "" : "disabled"} title="${canClose ? "关闭后只能查看" : "这一轮已经关了"}">关闭</button>
    <button type="button" role="menuitem" data-op="delete" data-op-id="${r.id}" class="is-danger"
      ${used ? "disabled" : ""} title="${used ? `还有 ${used} 条数据，只能关闭` : `删除 #${r.id}`}">删除</button>`;
  pop.hidden = false;

  // 面板只有 200px 宽，弹窗塞在里面必然盖住别的行或底部按钮，
  // 所以贴着面板右侧浮出，垂直对齐这一行；上下超出视口时再夹回来
  const menu = $("round-menu").getBoundingClientRect();
  const box = anchor.getBoundingClientRect();
  const height = pop.getBoundingClientRect().height;
  pop.style.left = (menu.width + 6) + "px";
  let top = box.top - menu.top + box.height / 2 - height / 2;
  top = Math.max(8 - menu.top, top);
  top = Math.min(top, window.innerHeight - 8 - height - menu.top);
  pop.style.top = top + "px";
}

/** 下拉底部的提示行。空字符串就藏起来。 */
function roundTip(text) {
  const tip = $("round-form-tip");
  tip.textContent = text || "";
  tip.hidden = !text;
}

/** 收起内嵌表单，回到「搜索框 + 列表 + 新建」。 */
function resetRoundDialog() {
  state.roundDialog = null;
  const form = $("round-form");
  form.hidden = true;
  form.reset();
  roundTip("");
  $("round-form-ok").disabled = false;
  $("round-search").hidden = false;
  $("round-list").hidden = false;
  $("round-actions").hidden = false;
}

/**
 * 新建和关闭共用一块表单：新建填名字，关闭填结论。
 * 关闭要指定是哪一轮——行内「…」里点的是某一行，不一定等于当前选中的轮。
 */
function openRoundDialog(mode, roundId = null) {
  const target = mode === "close"
    ? (roundId != null ? state.rounds.find((item) => item.id === roundId) : state.round)
    : null;
  if (mode === "close" && (!target || target.status !== "open")) return;
  const isNew = mode === "new";
  state.roundDialog = { mode, force: false, id: target ? target.id : null };
  closeRoundOps();
  $("round-search").hidden = true;
  $("round-list").hidden = true;
  $("round-actions").hidden = true;
  $("round-form").hidden = false;
  roundTip("");
  $("round-form-ok").disabled = false;
  $("round-form-title").textContent = isNew ? "新建轮次" : `关闭 #${target.id}「${target.name}」`;
  $("round-form-name").hidden = !isNew;
  $("round-form-name").value = "";
  $("round-form-note").value = "";
  $("round-form-note").placeholder = isNew ? "备注（可选）" : "本轮结论，关掉后只能查看";
  $("round-form-ok").textContent = isNew ? "创建" : "关闭本轮";
  (isNew ? $("round-form-name") : $("round-form-note")).focus();
}

/** 当前这一轮挂了多少条数据；删除和关闭都要看这个。 */
function roundDataCount(r) {
  if (!r || r.id == null) return 0;
  return Number(r.tasks || 0) + Number(r.results || 0) + Number(r.messages || 0);
}

function paintRound() {
  if (!$("round-name")) return;
  const r = state.round;
  $("round-name").textContent = r ? r.name : "未选择轮次";
  $("round-name").title = r ? r.name : "";
  $("round-meta").textContent = roundMetaText();
  const dot = $("round-dot");
  // 没选到轮次时别亮绿点，虚线圈表示「空」
  const dotState = !r ? " is-empty" : r.status === "closed" ? " is-closed" : r.status === "none" ? " is-empty" : "";
  dot.className = "round-dot" + dotState;
  if (state.roundMenuOpen) paintRoundList();
}

function setRoundMenu(open) {
  state.roundMenuOpen = open;
  $("round-menu").hidden = !open;
  $("round-switch").setAttribute("aria-expanded", open ? "true" : "false");
  if (open) {
    paintRoundList();
    $("round-search").focus();
  } else {
    state.roundQuery = "";
    $("round-search").value = "";
    closeRoundOps();
    resetRoundDialog();
  }
}

/** 建一轮：后端顺手建好 runs/<编号>-<名字>/，这里只负责切过去。 */
async function createRound(name, note) {
  const data = await postJSON("/rounds", { name, note });
  state.rounds = [data, ...state.rounds.filter((r) => r.id !== data.id)];
  state.round = data;
  Object.keys(state.listPage).forEach((kind) => { state.listPage[kind] = 1; });
  storeRound(data.id);
  resetRoundDialog();
  setRoundMenu(false);
  if (!setRoundParam(data.id)) refresh();
}

/** 关错了再启用回来。整份数据都不动，只把状态改回进行中。 */
async function enableRound(id) {
  try {
    const data = await postJSON("/rounds/" + id + "/reopen", {});
    const listIndex = state.rounds.findIndex((item) => item.id === id);
    if (listIndex >= 0) state.rounds[listIndex] = data;
    if (state.round && state.round.id === id) state.round = data;
    state.error = "";
  } catch (err) {
    state.error = String(err.message || err);
  }
  refresh();
}

async function closeRound(id, note, force) {
  const data = await postJSON("/rounds/" + id + "/close", { note, force: !!force });
  const listIndex = state.rounds.findIndex((item) => item.id === id);
  if (listIndex >= 0) state.rounds[listIndex] = data;
  // 等接口回来的这几百毫秒里可能已经切到别的轮，别把选中项改回去
  if (state.round && state.round.id === id) state.round = data;
  resetRoundDialog();
  setRoundMenu(false);
  refresh();
}

/** 只删空轮；有数据的轮按钮就是灰的，走到这里再兜一层。 */
async function deleteRound(id) {
  const target = state.rounds.find((item) => item.id === id);
  if (!target || roundDataCount(target)) return;
  const ok = window.confirm(
    `删除轮次 #${id}「${target.name}」？\n只删空轮，runs/ 下已建好的目录不会自动删。`
  );
  if (!ok) return;
  try {
    await delJSON("/rounds/" + id);
    state.error = "";
    if (state.round && state.round.id === id) {
      state.round = null;
      storeRound("");
      if (!setRoundParam("")) refresh();
      return;
    }
    refresh();
  } catch (err) {
    state.error = String(err.message || err);
  }
}

function render() {
  const id = pageId();
  // 侧栏链接带上当前轮次，翻页不会把选中的轮次弄丢
  const keep = state.round
    ? (state.round.id != null ? "?round=" + state.round.id : "?round=none")
    : "";
  document.querySelectorAll("#nav a").forEach((a) => {
    a.classList.toggle("active", a.dataset.page === id);
    const base = "#/" + a.dataset.page;
    a.setAttribute("href", a.dataset.page === "docs" ? base : base + keep);
  });
  paintRound();

  // 同一篇说明不重绘，避免轮询把阅读位置打回顶部
  const docsKey = id === "docs" ? location.hash : "";
  if (id === "docs" && $("page").dataset.docsKey === docsKey) {
    $("crumb").textContent = docsCrumb();
    $("clock").textContent = "静态说明";
    return;
  }

  const shots = id === "browsers" ? snapshotBrowserShots() : null;

  $("page").dataset.page = id;
  $("page").dataset.docsKey = docsKey;
  const html = views[id]();
  if (html) setPageHtml(html);

  if (id === "browsers") {
    restoreBrowserShots(shots);
    startBrowserShots({ restart: false });
  } else {
    stopBrowserShots();
  }

  if (id === "docs") {
    $("crumb").textContent = docsCrumb();
    $("clock").textContent = "静态说明";
  } else {
    $("crumb").textContent = PAGES[id];
    $("clock").innerHTML = state.error ? `<span class="error">${esc(state.error)}</span>` : "更新于 " + new Date().toLocaleTimeString();
  }
}

async function refresh() {
  const id = pageId();
  // 说明页是静态文案，不跟着轮询打业务接口；但侧栏的轮次卡片要跟着更新
  if (id === "docs") {
    try {
      await Promise.all([loadArticles(), refreshRounds()]);
    } catch (err) {
      state.error = String(err.message || err);
    }
  } else {
    try {
      await load();
    } catch (err) {
      state.error = String(err.message || err);
    }
  }
  render();
}

let searchTimer = 0;
function queueSearchRefresh() {
  clearTimeout(searchTimer);
  searchTimer = setTimeout(() => { refresh(); }, 300);
}

loadArticles();

window.addEventListener("hashchange", () => {
  if (pageId() === "docs" && !docsReady()) {
    loadArticles().then(render);
    return;
  }
  if (pageId() === "docs") {
    render();
    return;
  }
  refresh();
});

$("page").addEventListener("click", async (ev) => {
  const clip = ev.target.closest("[data-expand]");
  if (clip) {
    const key = clip.getAttribute("data-expand");
    if (!state.expanded) state.expanded = {};
    state.expanded[key] = !state.expanded[key];
    clip.classList.toggle("is-open", !!state.expanded[key]);
    return;
  }
  if (onPagerClick(ev)) {
    refresh();
    return;
  }
  if (await onDeleteClick(ev)) {
    refresh();
    return;
  }
  if (await onBrowsersAction(ev)) refresh();
});

$("page").addEventListener("input", (ev) => {
  const el = ev.target.closest("[data-search-kind]");
  if (!el) return;
  const kind = el.getAttribute("data-search-kind");
  const next = el.value;
  if ((state.listQuery[kind] || "") === next) return;
  state.listQuery[kind] = next;
  state.listPage[kind] = 1;
  queueSearchRefresh();
});

$("page").addEventListener("change", async (ev) => {
  if (onShotIntervalChange(ev)) return;
  if (await onBrowserNameCommit(ev)) {
    refresh();
    return;
  }
  const el = ev.target.closest("[data-filter-kind]");
  if (!el) return;
  const kind = el.getAttribute("data-filter-kind");
  const key = el.getAttribute("data-filter-key");
  if (!kind || !key) return;
  if (!state.listFilter[kind]) state.listFilter[kind] = {};
  const next = el.value;
  if ((state.listFilter[kind][key] || "") === next) return;
  state.listFilter[kind][key] = next;
  state.listPage[kind] = 1;
  refresh();
});

$("page").addEventListener("keydown", (ev) => {
  if (ev.key !== "Enter") return;
  const nameInput = ev.target.closest("[data-browser-name]");
  if (nameInput) {
    ev.preventDefault();
    nameInput.blur();
    return;
  }
  if (!ev.target.closest("[data-search-kind]")) return;
  ev.preventDefault();
  clearTimeout(searchTimer);
  refresh();
});

$("round-switch").addEventListener("click", (ev) => {
  ev.stopPropagation();
  setRoundMenu(!state.roundMenuOpen);
});

$("round-search").addEventListener("input", (ev) => {
  state.roundQuery = ev.target.value;
  paintRoundList();
});

$("round-list").addEventListener("click", (ev) => {
  // 行右侧的「…」先于「选中这一行」处理
  const more = ev.target.closest("[data-more]");
  if (more) {
    ev.stopPropagation();
    toggleRoundOps(Number(more.getAttribute("data-more")), more);
    return;
  }
  const btn = ev.target.closest("[data-round]");
  if (!btn) return;
  const value = btn.getAttribute("data-round");
  setRoundMenu(false);
  storeRound(value);
  // 换了轮次就从第 1 页看起，否则会停在上一轮才有的页码上
  Object.keys(state.listPage).forEach((kind) => { state.listPage[kind] = 1; });
  state.expanded = {};
  if (!setRoundParam(value)) refresh();
});

// 小弹窗跟列表滚动对不上位置，滚了就收
$("round-list").addEventListener("scroll", () => closeRoundOps());

$("round-ops").addEventListener("click", (ev) => {
  const btn = ev.target.closest("[data-op]");
  if (!btn || btn.disabled) return;
  ev.stopPropagation();
  const id = Number(btn.getAttribute("data-op-id"));
  const op = btn.getAttribute("data-op");
  closeRoundOps();
  if (op === "enable") enableRound(id);
  else if (op === "close") openRoundDialog("close", id);
  else if (op === "delete") deleteRound(id);
});

$("round-new").addEventListener("click", () => openRoundDialog("new"));
$("round-form-cancel").addEventListener("click", () => resetRoundDialog());

$("round-form").addEventListener("submit", async (ev) => {
  ev.preventDefault();
  const dlg = state.roundDialog;
  if (!dlg) return;
  const name = $("round-form-name").value.trim();
  const note = $("round-form-note").value.trim();
  if (dlg.mode === "new" && !name) {
    roundTip("先给这一轮起个名字，比如 崇州-26.11.18");
    $("round-form-name").focus();
    return;
  }
  if (dlg.mode === "close" && !note) {
    roundTip("关闭要写一句本轮结论，几轮之后靠它区分");
    $("round-form-note").focus();
    return;
  }
  // 还有任务没跑完时，第一次点只提示，第二次才带 force 真关
  const target = dlg.id != null ? state.rounds.find((item) => item.id === dlg.id) : null;
  const alive = dlg.mode === "close" && target ? Number(target.alive_tasks || 0) : 0;
  if (alive && !dlg.force) {
    dlg.force = true;
    roundTip(`还有 ${alive} 条任务没跑完，再点一次就强制关掉。`);
    $("round-form-ok").textContent = "确认关闭";
    return;
  }
  const ok = $("round-form-ok");
  ok.disabled = true;
  try {
    if (dlg.mode === "new") await createRound(name, note);
    else await closeRound(dlg.id, note, dlg.force);
  } catch (err) {
    roundTip(String(err.message || err));
  } finally {
    ok.disabled = false;
  }
});

document.addEventListener("click", (ev) => {
  // 点弹窗外面收弹窗；「…」自己会 toggle，不在这里抢
  if (!ev.target.closest("#round-ops") && !ev.target.closest("[data-more]")) closeRoundOps();
  if (state.roundMenuOpen && !ev.target.closest("#round-picker")) setRoundMenu(false);
});

document.addEventListener("keydown", (ev) => {
  if (ev.key !== "Escape" || !state.roundMenuOpen) return;
  // 一层一层退：小弹窗 → 表单 → 面板
  if (state.roundOps != null) {
    closeRoundOps();
    return;
  }
  if (state.roundDialog) {
    resetRoundDialog();
    return;
  }
  setRoundMenu(false);
});

if (!location.hash) location.hash = "#/dashboard";
refresh();
setInterval(refresh, 5000);
