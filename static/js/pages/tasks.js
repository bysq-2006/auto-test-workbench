/** 任务列表。给子代理派活、认领和改状态。 */

import { renderList } from "../list.js";
import { state } from "../state.js";
import { empty, esc, timeCell, clipCell } from "../util.js";

const STATUS_LABEL = {
  pending: "待处理",
  running: "进行中",
  done: "已完成",
  failed: "失败",
};

/** compact=true 时不显示「描述」列，给仪表盘这种窄位置用。 */
export function taskRows(items, limit, compact = false) {
  const rows = items.slice(0, limit || items.length);
  if (!rows.length) return empty("暂无任务");
  const descHead = compact ? "" : "<th>描述</th>";
  return `<table>
    <thead><tr><th>编号</th><th>标题</th>${descHead}<th>状态</th><th>负责人</th><th>时间</th></tr></thead>
    <tbody>${rows.map((item) => `<tr>
      <td>${esc(item.id)}</td>
      ${clipCell("tasks", item.id, "title", item.title)}
      ${compact ? "" : clipCell("tasks", item.id, "description", item.description)}
      <td><span class="tag ${esc(item.status)}">${esc(STATUS_LABEL[item.status] || item.status || "—")}</span></td>
      <td>${esc(item.assignee || item.agent_name || "—")}</td>
      ${timeCell(item.updated_at || item.created_at)}
    </tr>`).join("")}</tbody>
  </table>`;
}

function selected(current, value) {
  return current === value ? " selected" : "";
}

function tasksToolbar() {
  const q = state.listQuery.tasks || "";
  const status = (state.listFilter.tasks || {}).status || "";
  return `<div class="list-toolbar">
    <select id="filter-tasks-status" data-filter-kind="tasks" data-filter-key="status">
      <option value=""${selected(status, "")}>全部状态</option>
      <option value="pending"${selected(status, "pending")}>待处理</option>
      <option value="running"${selected(status, "running")}>进行中</option>
      <option value="done"${selected(status, "done")}>已完成</option>
      <option value="failed"${selected(status, "failed")}>失败</option>
    </select>
    <input id="filter-tasks-q" data-search-kind="tasks" type="search" placeholder="搜索标题、描述或负责人" value="${esc(q)}">
  </div>`;
}

export function renderTasks() {
  const body = state.tasks.length ? taskRows(state.tasks) : "";
  return renderList({
    kind: "tasks",
    title: "任务",
    emptyText: "暂无任务",
    toolbar: tasksToolbar(),
    body,
    total: state.tasksTotal,
  });
}
