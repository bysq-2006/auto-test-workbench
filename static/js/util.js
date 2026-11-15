/** 各页共用的 DOM 小工具。 */

import { state } from "./state.js";

export const $ = (id) => document.getElementById(id);

/** 拼进 innerHTML 之前转义，避免正文被当成标签。 */
export function esc(value) {
  return String(value ?? "").replace(/[&<>"']/g, (ch) => ({
    "&": "&amp;",
    "<": "&lt;",
    ">": "&gt;",
    '"': "&quot;",
    "'": "&#39;",
  }[ch]));
}

export function tag(status) {
  return `<span class="tag ${esc(status)}">${esc(status || "—")}</span>`;
}

export function empty(text) {
  return `<div class="empty">${esc(text)}</div>`;
}

/** 下拉选项是否选中。 */
export function selected(current, value) {
  return current === value ? " selected" : "";
}

/** 把后端的 UTC 时间做成「3 分钟前」这种相对说法。 */
export function timeAgo(iso) {
  if (!iso) return "—";
  const t = Date.parse(iso);
  if (!Number.isFinite(t)) return "—";
  const sec = Math.max(0, Math.round((Date.now() - t) / 1000));
  if (sec < 60) return "刚刚";
  const min = Math.floor(sec / 60);
  if (min < 60) return min + " 分钟前";
  const hour = Math.floor(min / 60);
  if (hour < 24) return hour + " 小时前";
  const day = Math.floor(hour / 24);
  if (day < 30) return day + " 天前";
  return new Date(t).toLocaleString("zh-CN", { hour12: false });
}

export function timeCell(iso) {
  if (!iso) return `<td class="time">—</td>`;
  const t = Date.parse(iso);
  const exact = Number.isFinite(t) ? new Date(t).toLocaleString("zh-CN", { hour12: false }) : "";
  return `<td class="time" title="${esc(exact)}">${esc(timeAgo(iso))}</td>`;
}


/** 长文本默认显示三行，点一下展开或收起。展开状态记在 state 里，轮询重绘后还在。 */
export function clipCell(kind, id, field, text) {
  const raw = text == null ? "" : String(text);
  if (!raw) return "<td>—</td>";
  const key = kind + ":" + id + ":" + field;
  const open = !!(state.expanded && state.expanded[key]);
  return '<td><span class="cell-clip' + (open ? " is-open" : "") + '" data-expand="' + esc(key) + '">' + esc(raw) + "</span></td>";
}
