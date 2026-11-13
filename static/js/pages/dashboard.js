/** 总览：待办提醒、六组数字、最近的结果、消息和任务。 */

import { state } from "../state.js";
import { esc, timeAgo } from "../util.js";
import { messageList } from "./messages.js";
import { resultRows } from "./results.js";
import { taskRows } from "./tasks.js";

const TASK = { pending: "待处理", running: "进行中", done: "完成", failed: "失败" };
const BROWSER = { idle: "空闲", occupied: "占用中", closed: "已关闭" };

const TASK_COLOR = { pending: "#9ca3af", running: "#3b82f6", done: "#16a34a", failed: "#dc2626" };
const BROWSER_COLOR = { idle: "#16a34a", occupied: "#f97316", closed: "#d1d5db" };

/** 一条按数量占比的色带；全为 0 时留一条空槽，避免卡片高度跳动。 */
function colorBar(segments) {
  const total = segments.reduce((sum, seg) => sum + seg[1], 0);
  if (!total) return `<div class="stat-bar"></div>`;
  const parts = segments
    .filter((seg) => seg[1] > 0)
    .map((seg) => {
      const width = (seg[1] / total) * 100;
      return `<i style="background:${seg[2]};width:${width.toFixed(2)}%" title="${esc(seg[0])} ${seg[1]}"></i>`;
    })
    .join("");
  return `<div class="stat-bar">${parts}</div>`;
}

/** 卡片下方的一行小字：名称 + 数字，数字加粗。 */
function legend(pairs) {
  if (!pairs.length) return "";
  const items = pairs
    .map(([label, value, muted]) =>
      `<span${muted ? ' class="muted"' : ""}>${esc(label)} <b>${esc(value)}</b></span>`)
    .join("");
  return `<div class="stat-sub">${items}</div>`;
}

function statCard({ label, value, hint, bar, sub }) {
  return `<div class="stat">
    <div class="stat-top">
      <span class="label">${esc(label)}</span>
      ${hint ? `<span class="hint">${esc(hint)}</span>` : ""}
    </div>
    <b class="num">${esc(value)}</b>
    ${bar || ""}
    ${sub || ""}
  </div>`;
}

/** 顶部只提示"现在该处理什么"，点一下跳到对应页。没有待办就说没有。 */
function todoChips(tasks, notes, browsers) {
  const items = [];
  if (tasks.pending) items.push(["#/tasks", `<b>${tasks.pending}</b> 个任务待认领`]);
  if (tasks.running) items.push(["#/tasks", `<b class="ok">${tasks.running}</b> 个任务进行中`]);
  if (tasks.failed) items.push(["#/tasks", `<b class="warn">${tasks.failed}</b> 个任务失败`]);
  if (notes.pending) items.push(["#/results", `<b class="warn">${notes.pending}</b> 条提案待审`]);
  if (browsers.occupied) items.push(["#/browsers", `<b class="warn">${browsers.occupied}</b> 台资源被占用`]);
  if (!items.length) items.push(["#/tasks", `<b class="ok">没有</b> 待处理事项`]);
  return items
    .map(([href, html]) => `<a class="chip" href="${href}">${html}</a>`)
    .join("");
}

export function renderDashboard() {
  const t = state.status.tasks || { pending: 0, running: 0, done: 0, failed: 0 };
  const r = state.status.results || { pass: 0, fail: 0 };
  const n = state.status.notes || { total: 0, pending: 0 };
  const b = state.status.browsers || { idle: 0, occupied: 0, closed: 0 };

  const skillCount = state.skillsTotal;
  const msgCount = state.messagesTotal;
  const taskCount = t.pending + t.running + t.done + t.failed;
  const testCount = r.pass + r.fail;
  const rate = testCount ? Math.round((r.pass / testCount) * 100) : 0;
  const browserCount = b.idle + b.occupied + b.closed;
  const latestSkill = state.skills[0];
  const latestMsg = state.messages[0];

  return `
    <section class="hero">
      <h1>欢迎回来</h1>
      <div class="chips">${todoChips(t, n, b)}</div>
    </section>
    <section class="stats">
      ${statCard({
        label: "技能",
        value: skillCount,
        hint: "现场扫描",
        sub: legend(latestSkill ? [["最新", latestSkill.name || latestSkill.path || "—"]] : []),
      })}
      ${statCard({
        label: "任务",
        value: taskCount,
        hint: t.running ? `${t.running} 个在跑` : "",
        bar: colorBar(Object.keys(TASK).map((k) => [TASK[k], t[k] || 0, TASK_COLOR[k]])),
        sub: legend(Object.keys(TASK).map((k) => [TASK[k], t[k] || 0, !t[k]])),
      })}
      ${statCard({
        label: "测试结果",
        value: testCount,
        hint: testCount ? `通过率 ${rate}%` : "",
        bar: colorBar([["通过", r.pass, "#16a34a"], ["失败", r.fail, "#dc2626"]]),
        sub: legend([["通过", r.pass, !r.pass], ["失败", r.fail, !r.fail]]),
      })}
      ${statCard({
        label: "提案",
        value: n.total,
        hint: n.pending ? `${n.pending} 条待审` : "",
        bar: colorBar([
          ["待审", n.pending, "#f97316"],
          ["已处理", Math.max(0, n.total - n.pending), "#d1d5db"],
        ]),
        sub: legend([["待审", n.pending, !n.pending], ["已处理", Math.max(0, n.total - n.pending), true]]),
      })}
      ${statCard({
        label: "资源",
        value: browserCount,
        hint: b.occupied ? `${b.occupied} 台在用` : "",
        bar: colorBar(Object.keys(BROWSER).map((k) => [BROWSER[k], b[k] || 0, BROWSER_COLOR[k]])),
        sub: legend(Object.keys(BROWSER).map((k) => [BROWSER[k], b[k] || 0, !b[k]])),
      })}
      ${statCard({
        label: "消息",
        value: msgCount,
        hint: "公共聊天厅",
        sub: legend(latestMsg
          ? [["最近", latestMsg.name || "匿名"], ["时间", timeAgo(latestMsg.created_at)]]
          : []),
      })}
    </section>
    <section class="dash-grid">
      <div class="card">
        <div class="card-head"><h2>最近结果</h2><a class="more" href="#/results">全部</a></div>
        ${resultRows(state.results, 8)}
      </div>
      <div class="card">
        <div class="card-head"><h2>最近消息</h2><a class="more" href="#/messages">全部</a></div>
        ${messageList(state.messages, 8)}
      </div>
    </section>
    <section class="card dash-wide">
      <div class="card-head"><h2>最近任务</h2><a class="more" href="#/tasks">全部</a></div>
      ${taskRows(state.tasks, 6, true)}
    </section>
  `;
}
