/** 公共聊天厅。可按发送者或正文搜索，方便找 ISSUE。 */

import { actionCell, actionHead, renderList } from "../list.js";
import { state } from "../state.js";
import { empty, esc, timeCell, clipCell } from "../util.js";

/** compact=true 时不显示删除按钮，给仪表盘预览用。 */
export function messageList(items, limit, compact = false) {
  const rows = items.slice(0, limit || items.length);
  if (!rows.length) return empty("暂无消息");
  return `<table>
    <thead><tr><th>发送者</th><th>内容</th><th>时间</th>${compact ? "" : actionHead()}</tr></thead>
    <tbody>${rows.map((msg) => `<tr>
      <td>${esc(msg.name || "匿名")}</td>
      ${clipCell("messages", msg.id, "body", msg.body)}
      ${timeCell(msg.created_at)}
      ${compact ? "" : actionCell("messages", msg.id)}
    </tr>`).join("")}</tbody>
  </table>`;
}

function messagesToolbar() {
  const q = state.listQuery.messages || "";
  return `<div class="list-toolbar">
    <input id="filter-messages-q" data-search-kind="messages" type="search" placeholder="搜索发送者或内容，如 ISSUE、blocker" value="${esc(q)}">
  </div>`;
}

export function renderMessages() {
  const body = state.messages.length ? messageList(state.messages) : "";
  return renderList({
    kind: "messages",
    title: "消息",
    emptyText: "暂无消息",
    toolbar: messagesToolbar(),
    body,
    total: state.messagesTotal,
  });
}
