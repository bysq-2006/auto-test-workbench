/** 各列表共用标题、卡片和分页。筛选和搜索由各页自己写。 */

import { LIST_PAGE_SIZE, state } from "./state.js";
import { esc } from "./util.js";

export function pager(kind, total) {
  const pages = Math.max(1, Math.ceil(total / LIST_PAGE_SIZE) || 1);
  const page = Math.min(state.listPage[kind] || 1, pages);
  return `<div class="pager">
    <button type="button" data-list="${kind}" data-page="${page - 1}" ${page <= 1 ? "disabled" : ""}>上一页</button>
    <span>第 ${page} / ${pages} 页</span>
    <button type="button" data-list="${kind}" data-page="${page + 1}" ${page >= pages ? "disabled" : ""}>下一页</button>
  </div>`;
}

/** 带标题、可选工具栏、内容和分页的一页列表。 */
export function renderList({ kind, title, emptyText, toolbar, body, total }) {
  const content = body || `<div class="empty">${esc(emptyText)}</div>`;
  return `<h1 class="page-title">${esc(title)}</h1>
    <div class="card">
      ${toolbar || ""}
      ${content}
      ${pager(kind, total)}
    </div>`;
}

/** 点分页时改对应列表的页码。 */
export function onPagerClick(ev) {
  const btn = ev.target.closest("button[data-list][data-page]");
  if (!btn || btn.disabled) return false;
  const kind = btn.getAttribute("data-list");
  const next = Number(btn.getAttribute("data-page"));
  if (!state.listPage[kind] || !Number.isFinite(next) || next < 1 || next === state.listPage[kind]) return false;
  state.listPage[kind] = next;
  return true;
}
