const $ = (id) => document.getElementById(id);

function esc(value) {
  return String(value ?? "").replace(/[&<>"]/g, (ch) => ({
    "&": "&amp;",
    "<": "&lt;",
    ">": "&gt;",
    '"': "&quot;",
  }[ch]));
}

function firstLine(text) {
  return String(text || "").split("\n")[0];
}

async function getJSON(url) {
  const res = await fetch(url);
  if (!res.ok) throw new Error(url + " -> " + res.status);
  return res.json();
}

function table(headers, rowsHtml) {
  if (!rowsHtml.length) return '<p class="muted">暂无</p>';
  const head = headers.map((item) => `<th>${esc(item)}</th>`).join("");
  return `<table><thead><tr>${head}</tr></thead><tbody>${rowsHtml.join("")}</tbody></table>`;
}

let chart;

function drawChart(tasks) {
  if (typeof Chart === "undefined") return;
  const data = [tasks.pending, tasks.running, tasks.done, tasks.failed];
  if (!chart) {
    chart = new Chart($("chart"), {
      type: "bar",
      data: {
        labels: ["pending", "running", "done", "failed"],
        datasets: [{
          label: "任务数",
          data,
          backgroundColor: ["#94a3b8", "#3b82f6", "#16a34a", "#dc2626"],
        }],
      },
      options: {
        responsive: true,
        plugins: { legend: { display: false } },
        scales: { y: { beginAtZero: true, ticks: { precision: 0 } } },
      },
    });
    return;
  }
  chart.data.datasets[0].data = data;
  chart.update();
}

async function refresh() {
  const [status, skills, tasks, results, claims, messages] = await Promise.all([
    getJSON("/api/status"),
    getJSON("/skills"),
    getJSON("/tasks?limit=20"),
    getJSON("/test-results?limit=20"),
    getJSON("/claims?status=held"),
    getJSON("/messages?limit=20"),
  ]);

  $("cards").innerHTML = [
    ["待处理", status.tasks.pending],
    ["进行中", status.tasks.running],
    ["测试通过", status.results.pass],
    ["占用中的资源", status.claims_held],
  ].map(([label, value]) => `<div class="card"><span class="muted">${esc(label)}</span><b>${esc(value)}</b></div>`).join("");

  drawChart(status.tasks);

  $("skills").innerHTML = skills.length
    ? skills.map((skill) => `<li><code>${esc(skill.path)}</code> — ${esc(firstLine(skill.description))}</li>`).join("")
    : '<li class="muted">暂无技能</li>';

  $("tasks").innerHTML = table(
    ["ID", "状态", "认领者", "标题"],
    tasks.map((task) => `<tr><td>${task.id}</td><td class="tag">${esc(task.status)}</td><td>${esc(task.assignee || "—")}</td><td>${esc(task.title)}</td></tr>`),
  );

  $("results").innerHTML = table(
    ["代理", "结果", "摘要"],
    results.map((item) => `<tr><td>${esc(item.agent_name)}</td><td class="tag">${esc(item.status)}</td><td>${esc(item.summary)}</td></tr>`),
  );

  $("claims").innerHTML = claims.length
    ? claims.map((claim) => `<li><code>${esc(claim.resource)}</code> ← ${esc(claim.owner)}</li>`).join("")
    : '<li class="muted">没有占用</li>';

  $("messages").innerHTML = messages.length
    ? messages.map((msg) => `<li><b>${esc(msg.from_agent)}</b> → ${esc(msg.to_agent || "所有人")}: ${esc(msg.body)}</li>`).join("")
    : '<li class="muted">暂无消息</li>';

  $("clock").textContent = "更新于 " + new Date().toLocaleString();
}

refresh().catch((err) => {
  $("clock").textContent = String(err);
});
setInterval(() => {
  refresh().catch((err) => {
    $("clock").textContent = String(err);
  });
}, 3000);
