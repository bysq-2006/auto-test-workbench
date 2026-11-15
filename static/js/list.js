/** 各列表共用标题、卡片和分页。筛选和搜索由各页自己写。 */

import { delJSON } from "./api.js";
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

const DELETE_PATH = {
  tasks: "/tasks",
  results: "/results",
  messages: "/messages",
};

const DELETE_LABEL = {
  tasks: "任务",
  results: "结果",
  messages: "消息",
};

/** 表头。列表页统一在最后一列放删除按钮。 */
export function actionHead() {
  return "<th></th>";
}

/** 行尾的删除按钮后面那一格。 */
export function actionCell(kind, id) {
  if (!DELETE_PATH[kind]) return "<td></td>";
  return `<td class="row-action-cell"><button type="button" class="row-action is-danger"
    data-del-kind="${esc(kind)}" data-del-id="${esc(id)}">删除</button></td>`;
}

/** 点删除按钮：先确认，再打 DELETE，成功返回 true 让调用方重绘。 */
export async function onDeleteClick(ev) {
  const btn = ev.target.closest("[data-del-kind]");
  if (!btn || btn.disabled) return false;
  const kind = btn.getAttribute("data-del-kind");
  const id = Number(btn.getAttribute("data-del-id"));
  const path = DELETE_PATH[kind];
  if (!path || !Number.isFinite(id) || id < 1) return false;
  if (!window.confirm(`删除${DELETE_LABEL[kind]} #${id}？删了找不回来。`)) return false;
  btn.disabled = true;
  try {
    await delJSON(path + "/" + id);
    state.error = "";
  } catch (err) {
    state.error = String(err.message || err);
  }
  return true;
}
