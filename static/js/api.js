/** 请求后端接口。技能走文件扫描，结果、消息、任务和资源走数据库。 */

import { LIST_PAGE_SIZE, state } from "./state.js";
import { pageId, roundParam } from "./router.js";

const ROUND_KEY = "workbench.round";

function errorFromResponse(url, res, data) {
  const detail = data && data.detail;
  if (typeof detail === "string" && detail.trim()) return detail;
  return url + " -> " + res.status;
}

/** 拉取 JSON。失败时带上地址和状态码，顶栏会显示。 */
export async function getJSON(url) {
  const res = await fetch(url);
  if (!res.ok) {
    let data = null;
    try { data = await res.json(); } catch (err) { /* 非 JSON */ }
    throw new Error(errorFromResponse(url, res, data));
  }
  return res.json();
}

/** POST JSON。失败时尽量带上后端的 detail。 */
export async function postJSON(url, body) {
  const res = await fetch(url, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body ?? {}),
  });
  if (!res.ok) {
    let data = null;
    try { data = await res.json(); } catch (err) { /* 非 JSON */ }
    throw new Error(errorFromResponse(url, res, data));
  }
  if (res.status === 204) return null;
  return res.json();
}

/** DELETE。204 视为成功返回 null，其余按 JSON 解析。 */
export async function delJSON(url) {
  const res = await fetch(url, { method: "DELETE" });
  if (!res.ok) {
    let data = null;
    try { data = await res.json(); } catch (err) { /* 非 JSON */ }
    throw new Error(errorFromResponse(url, res, data));
  }
  if (res.status === 204) return null;
  return res.json();
}

/** 把分页接口统一收成 items + total，兼容偶尔返回的旧数组。 */
export function applyList(kind, data) {
  if (Array.isArray(data)) {
    state[kind] = data;
    state[kind + "Total"] = data.length;
    return;
  }
  state[kind] = data.items || [];
  state[kind + "Total"] = Number(data.total || 0);
}

/** 发给后端的 round 值：编号、"none"（未归类）。没选轮次时也按未归类查。 */
export function roundValue() {
  return state.round && state.round.id != null ? String(state.round.id) : "none";
}

function looseTotal() {
  const u = state.roundsUnassigned || {};
  return Number(u.tasks || 0) + Number(u.results || 0) + Number(u.messages || 0);
}

function readStoredRound() {
  try { return localStorage.getItem(ROUND_KEY) || ""; } catch (err) { return ""; }
}

/** 记住上一次看的是哪一轮；链接里带了 round 时以链接为准。 */
export function storeRound(value) {
  try { localStorage.setItem(ROUND_KEY, String(value ?? "")); } catch (err) { /* 隐私模式 */ }
}

function findRound(value) {
  if (!value) return null;
  if (value === "none") {
    return looseTotal() ? { id: null, name: "未归类", status: "none" } : null;
  }
  const id = Number(value);
  if (!Number.isFinite(id)) return null;
  return state.rounds.find((item) => item.id === id) || null;
}

/** 优先级：链接里的 round > 上次看的 > 最新一轮。都没有就是空。 */
function resolveRound() {
  return findRound(roundParam()) || findRound(readStoredRound()) || state.rounds[0] || null;
}

function applyRounds(data) {
  state.rounds = data.items || [];
  state.roundsUnassigned = data.unassigned || { tasks: 0, results: 0, messages: 0 };
  state.round = resolveRound();
}

const LIST_PATH = {
  skills: "/skills",
  tasks: "/tasks",
  results: "/results",
  messages: "/messages",
  browsers: "/browsers",
};

/** 当前页才带上这一页的搜索和筛选；仪表盘预览不加。任务、结果、消息都按轮次筛。 */
export function listExtra(kind) {
  const extra = {};
  const q = (state.listQuery[kind] || "").trim();
  if (q) extra.q = q;
  const f = state.listFilter[kind] || {};
  if (kind === "tasks" && f.status) extra.status = f.status;
  if (kind === "results") {
    if (f.kind) extra.kind = f.kind;
    if (f.recorded) extra.recorded = f.recorded;
  }
  if (kind === "browsers" && f.status) extra.status = f.status;
  if (kind === "tasks" || kind === "results" || kind === "messages") extra.round = roundValue();
  return extra;
}

function listUrl(path, page, limit, extra = {}) {
  const params = new URLSearchParams({ limit: String(limit), page: String(page) });
  Object.entries(extra).forEach(([key, value]) => {
    if (value != null && String(value).trim() !== "") params.set(key, String(value).trim());
  });
  return `${path}?${params}`;
}

/** 只要轮次列表。说明页不打业务接口，但侧栏的轮次卡片得有内容。 */
export async function refreshRounds() {
  applyRounds(await getJSON("/rounds"));
}

/**
 * 并行拉状态和各列表。
 * 先拿轮次列表，确定这一屏看哪一轮，后面的列表和统计都按它筛。
 */
export async function load() {
  const id = pageId();
  applyRounds(await getJSON("/rounds"));

  const urlFor = (kind, previewLimit) => {
    if (id === kind) {
      return listUrl(LIST_PATH[kind], state.listPage[kind], LIST_PAGE_SIZE, listExtra(kind));
    }
    // 预览只要「最近几条」，不带本页的搜索和筛选；但轮次必须带，否则会混别的轮
    const preview = (kind === "tasks" || kind === "results" || kind === "messages")
      ? { round: roundValue() }
      : {};
    return listUrl(LIST_PATH[kind], 1, previewLimit, preview);
  };
  const statusUrl = "/api/status?" + new URLSearchParams({ round: roundValue() });
  const skillUrl = urlFor("skills", 1);
  const taskUrl = urlFor("tasks", 8);
  const resultUrl = urlFor("results", 8);
  const msgUrl = urlFor("messages", 8);
  const browserUrl = urlFor("browsers", 1);
  const settled = await Promise.allSettled([
    getJSON(statusUrl),
    getJSON(skillUrl),
    getJSON(taskUrl),
    getJSON(resultUrl),
    getJSON(msgUrl),
    getJSON(browserUrl),
  ]);
  const keys = ["status", "skills", "tasks", "results", "messages", "browsers"];
  const errors = [];
  settled.forEach((item, i) => {
    if (item.status === "fulfilled") {
      if (keys[i] === "status") state.status = item.value;
      else applyList(keys[i], item.value);
    } else {
      errors.push(String(item.reason?.message || item.reason));
    }
  });
  state.error = errors[0] || "";

  // 删除后当前页可能超出总页数，拉回最后一页
  if (LIST_PATH[id]) {
    const total = state[id + "Total"];
    const pages = Math.max(1, Math.ceil(total / LIST_PAGE_SIZE) || 1);
    if (state.listPage[id] > pages) {
      state.listPage[id] = pages;
      applyList(id, await getJSON(listUrl(LIST_PATH[id], state.listPage[id], LIST_PAGE_SIZE, listExtra(id))));
    }
  }
}
