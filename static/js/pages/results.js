/** 子代理回写结果。测试通过/失败是其中一种，也可以记普通结果。 */

import { renderList } from "../list.js";
import { state } from "../state.js";
import { empty, esc, tag, timeCell, clipCell } from "../util.js";

const KIND_LABEL = { test: "测试", note: "通用" };

export function resultRows(items, limit) {
  const rows = items.slice(0, limit || items.length);
  if (!rows.length) return empty("暂无结果");
  return `<table>
    <thead><tr><th>代理</th><th>类型</th><th>绑定的任务</th><th>内容</th><th>状态</th><th>主 AI 记录</th><th>时间</th></tr></thead>
    <tbody>${rows.map((item) => `<tr>
      <td>${esc(item.agent_name)}</td>
      <td>${esc(KIND_LABEL[item.kind] || item.kind || "通用")}</td>
      ${clipCell("results", item.id, "task", item.task_title || (item.task_id != null ? "#" + item.task_id : ""))}
      ${clipCell("results", item.id, "summary", item.summary)}
      <td>${item.status ? tag(item.status) : "—"}</td>
      <td>${item.recorded ? '<span class="tag done">已记录</span>' : '<span class="tag pending">未记录</span>'}</td>
      ${timeCell(item.created_at)}
    </tr>`).join("")}</tbody>
  </table>`;
}

function selected(current, value) {
  return current === value ? " selected" : "";
}

function resultsToolbar() {
  const q = state.listQuery.results || "";
  const f = state.listFilter.results || {};
  const kind = f.kind || "";
  const recorded = f.recorded || "";
  return `<div class="list-toolbar">
    <select id="filter-results-kind" data-filter-kind="results" data-filter-key="kind">
      <option value=""${selected(kind, "")}>全部类型</option>
      <option value="test"${selected(kind, "test")}>测试</option>
      <option value="note"${selected(kind, "note")}>通用</option>
    </select>
    <select id="filter-results-recorded" data-filter-kind="results" data-filter-key="recorded">
      <option value=""${selected(recorded, "")}>记录状态</option>
      <option value="false"${selected(recorded, "false")}>未记录</option>
      <option value="true"${selected(recorded, "true")}>已记录</option>
    </select>
    <input id="filter-results-q" data-search-kind="results" type="search" placeholder="搜索代理、内容或任务" value="${esc(q)}">
  </div>`;
}

export function renderResults() {
  const body = state.results.length ? resultRows(state.results) : "";
  return renderList({
    kind: "results",
    title: "结果",
    emptyText: "暂无结果",
    toolbar: resultsToolbar(),
    body,
    total: state.resultsTotal,
  });
}
