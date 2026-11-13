/** 入口：挂上路由、分页和各页自己的筛选搜索，启动后每 5 秒刷新一次数据。 */

import { load } from "./api.js";
import { docsCrumb, docsReady, loadArticles, renderDocs } from "./docs.js";
import { onPagerClick } from "./list.js";
import { renderDashboard } from "./pages/dashboard.js";
import {
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
import { PAGES, pageId } from "./router.js";
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
  } : null;
  page.innerHTML = html;
  if (!restore) return;
  const el = document.getElementById(restore.id);
  if (!el) return;
  el.focus();
  if (typeof restore.start === "number" && typeof el.setSelectionRange === "function") {
    try { el.setSelectionRange(restore.start, restore.end); } catch (err) { /* 下拉框没有选区 */ }
  }
}

function render() {
  const id = pageId();
  document.querySelectorAll("#nav a").forEach((a) => a.classList.toggle("active", a.dataset.page === id));

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
  // 说明页是静态文案，不跟着轮询打接口；文章没到之前先不画空白页
  if (id === "docs") {
    await loadArticles();
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

$("page").addEventListener("change", (ev) => {
  if (onShotIntervalChange(ev)) return;
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
  if (!ev.target.closest("[data-search-kind]")) return;
  ev.preventDefault();
  clearTimeout(searchTimer);
  refresh();
});

if (!location.hash) location.hash = "#/dashboard";
refresh();
setInterval(refresh, 5000);
