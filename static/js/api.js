/** 请求后端接口。技能走文件扫描，结果、消息、任务和资源走数据库。 */

import { LIST_PAGE_SIZE, state } from "./state.js";
import { pageId } from "./router.js";

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

const LIST_PATH = {
  skills: "/skills",
  tasks: "/tasks",
  results: "/results",
  messages: "/messages",
  browsers: "/browsers",
};

/** 当前页才带上这一页的搜索和筛选；仪表盘预览不加。 */
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
  return extra;
}

function listUrl(path, page, limit, extra = {}) {
  const params = new URLSearchParams({ limit: String(limit), page: String(page) });
  Object.entries(extra).forEach(([key, value]) => {
    if (value != null && String(value).trim() !== "") params.set(key, String(value).trim());
  });
  return `${path}?${params}`;
}

/**
 * 并行拉状态和各列表。
 * 当前页带上自己的页码、搜索和筛选，轮询不会把列表打回第 1 页。
 */
export async function load() {
  const id = pageId();
  const urlFor = (kind, previewLimit) => {
    if (id === kind) {
      return listUrl(LIST_PATH[kind], state.listPage[kind], LIST_PAGE_SIZE, listExtra(kind));
    }
    return listUrl(LIST_PATH[kind], 1, previewLimit);
  };
  const skillUrl = urlFor("skills", 1);
  const taskUrl = urlFor("tasks", 8);
  const resultUrl = urlFor("results", 8);
  const msgUrl = urlFor("messages", 8);
  const browserUrl = urlFor("browsers", 1);
  const settled = await Promise.allSettled([
    getJSON("/api/status"),
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
