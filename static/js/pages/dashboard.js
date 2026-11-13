/** 总览：技能数量、通过和失败、最近的结果和消息。 */

import { state } from "../state.js";
import { spark } from "../util.js";
import { messageList } from "./messages.js";
import { resultRows } from "./results.js";

export function renderDashboard() {
  const r = state.status.results || { pass: 0, fail: 0 };
  const n = state.status.notes || { total: 0, pending: 0 };
  const skillCount = state.skillsTotal;
  const taskCount = state.tasksTotal;
  const msgCount = state.messagesTotal;
  return `
    <section class="hero">
      <h1>欢迎回来</h1>
      <div class="chips">
        <span class="chip"><b>${skillCount}</b> 个技能</span>
        <span class="chip"><b>${taskCount}</b> 个任务</span>
        <span class="chip"><b class="ok">${r.pass}</b> 条通过</span>
        <span class="chip"><b class="warn">${r.fail}</b> 条失败</span>
        ${n.pending ? `<span class="chip"><b class="warn">${n.pending}</b> 条待审提案</span>` : ""}
      </div>
    </section>
    <section class="stats">
      <div class="stat"><div><div class="label">技能</div><b class="num">${skillCount}</b></div>${spark("blue", [1, skillCount, skillCount, skillCount])}</div>
      <div class="stat"><div><div class="label">测试通过</div><b class="num">${r.pass}</b></div>${spark("green", [r.fail, r.pass, r.pass, r.pass])}</div>
      <div class="stat"><div><div class="label">消息</div><b class="num">${msgCount}</b></div>${spark("orange", [1, 2, msgCount, msgCount])}</div>
    </section>
    <section class="dash-grid">
      <div class="card">
        <div class="card-head"><h2>最近结果</h2></div>
        ${resultRows(state.results, 8)}
      </div>
      <div class="card">
        <div class="card-head"><h2>最近消息</h2></div>
        ${messageList(state.messages, 8)}
      </div>
    </section>
  `;
}
