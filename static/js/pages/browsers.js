/** 浏览器资源：小电脑卡片，横排两个，屏幕按设定间隔抓画面。 */

import { delJSON, postJSON } from "../api.js";
import { renderList } from "../list.js";
import { state } from "../state.js";
import { empty, esc, timeAgo } from "../util.js";

const STATUS_LABEL = {
  idle: "空闲",
  occupied: "占用",
  closed: "已关闭",
};

const INTERVAL_KEY = "wb-browser-shot-interval";
const MIN_INTERVAL = 0.5;
const MAX_INTERVAL = 60;
const DEFAULT_INTERVAL = 1;

let shotTimer = 0;
const inflight = new Set();

function clampInterval(value) {
  const n = Number(value);
  if (!Number.isFinite(n)) return DEFAULT_INTERVAL;
  return Math.min(MAX_INTERVAL, Math.max(MIN_INTERVAL, n));
}

function shotInterval() {
  loadShotInterval();
  return clampInterval(state.shotInterval);
}

export function loadShotInterval() {
  if (state.shotInterval != null) return;
  try {
    state.shotInterval = clampInterval(localStorage.getItem(INTERVAL_KEY));
  } catch (err) {
    state.shotInterval = DEFAULT_INTERVAL;
  }
}

export function saveShotInterval(value) {
  const n = clampInterval(value);
  state.shotInterval = n;
  try { localStorage.setItem(INTERVAL_KEY, String(n)); } catch (err) { /* 无本地存储就只记在内存 */ }
  return n;
}

function pcCard(item) {
  const closed = item.status === "closed";
  const status = STATUS_LABEL[item.status] || item.status || "—";
  const when = item.updated_at || item.created_at;
  return `<article class="pc-card" data-browser-id="${esc(item.id)}" data-browser-status="${esc(item.status)}">
    <div class="pc-body">
      <div class="pc-bezel">
        <div class="pc-screen${closed ? " is-off" : ""}">
          <div class="pc-placeholder">${closed ? "已关闭" : "等待画面"}</div>
          ${closed ? "" : `<img alt="端口 ${esc(item.port)} 的画面" data-browser-shot="${esc(item.id)}">`}
        </div>
      </div>
      <div class="pc-neck" aria-hidden="true"></div>
      <div class="pc-base" aria-hidden="true"></div>
    </div>
    <div class="pc-meta">
      <div class="pc-meta-top">
        <span class="pc-port">端口 ${esc(item.port)}</span>
        <span class="tag ${esc(item.status)}">${esc(status)}</span>
      </div>
      <div class="pc-meta-sub">
        <span>${esc(item.agent_name || "未占用")}${when ? " · " + esc(timeAgo(when)) : ""}</span>
        <span class="pc-actions">
          ${closed
            ? `<button type="button" class="row-action" data-browser-power="${esc(item.id)}">开机</button>
               <button type="button" class="row-action is-danger" data-browser-delete="${esc(item.id)}">删除</button>`
            : `<button type="button" class="row-action" data-browser-close="${esc(item.id)}">关闭</button>`}
        </span>
      </div>
    </div>
  </article>`;
}

export function browserRows(items, limit) {
  const rows = items.slice(0, limit || items.length);
  if (!rows.length) return empty("暂无资源");
  return `<div class="pc-grid">${rows.map(pcCard).join("")}</div>`;
}

function selected(current, value) {
  return current === value ? " selected" : "";
}

function browsersToolbar() {
  const q = state.listQuery.browsers || "";
  const status = (state.listFilter.browsers || {}).status || "";
  const interval = shotInterval();
  return `<div class="list-toolbar">
    <select id="filter-browsers-status" data-filter-kind="browsers" data-filter-key="status">
      <option value=""${selected(status, "")}>全部状态</option>
      <option value="idle"${selected(status, "idle")}>空闲</option>
      <option value="occupied"${selected(status, "occupied")}>占用</option>
      <option value="closed"${selected(status, "closed")}>已关闭</option>
    </select>
    <input id="filter-browsers-q" data-search-kind="browsers" type="search" placeholder="搜索端口或使用者" value="${esc(q)}">
    <label class="shot-interval">抓屏间隔
      <input id="filter-browsers-interval" data-shot-interval type="number" min="${MIN_INTERVAL}" max="${MAX_INTERVAL}" step="0.5" value="${esc(interval)}">
      秒
    </label>
    <button type="button" data-browser-start>启动浏览器</button>
  </div>`;
}

export function renderBrowsers() {
  const body = state.browsers.length ? browserRows(state.browsers) : "";
  return renderList({
    kind: "browsers",
    title: "资源",
    emptyText: "暂无资源",
    toolbar: browsersToolbar(),
    body,
    total: state.browsersTotal,
  });
}

export function snapshotBrowserShots() {
  const prev = {};
  document.querySelectorAll("img[data-browser-shot]").forEach((img) => {
    const id = img.getAttribute("data-browser-shot");
    const src = img.getAttribute("src");
    if (id && src) prev[id] = src;
  });
  return prev;
}

export function restoreBrowserShots(prev) {
  if (!prev) return;
  document.querySelectorAll("img[data-browser-shot]").forEach((img) => {
    const src = prev[img.getAttribute("data-browser-shot")];
    if (src) {
      img.src = src;
      img.closest(".pc-screen")?.classList.remove("is-off", "is-fail");
    }
  });
}

export function tickBrowserShots(opts = {}) {
  document.querySelectorAll("img[data-browser-shot]").forEach((img) => {
    const id = img.getAttribute("data-browser-shot");
    if (!id || inflight.has(id)) return;
    const card = img.closest(".pc-card");
    if (card && card.getAttribute("data-browser-status") === "closed") return;
    if (opts.onlyEmpty && img.getAttribute("src")) return;
    inflight.add(id);
    const probe = new Image();
    probe.onload = () => {
      img.src = probe.src;
      img.closest(".pc-screen")?.classList.remove("is-off", "is-fail");
      inflight.delete(id);
    };
    probe.onerror = () => {
      if (!img.getAttribute("src")) {
        const screen = img.closest(".pc-screen");
        screen?.classList.add("is-fail");
        const ph = screen?.querySelector(".pc-placeholder");
        if (ph) ph.textContent = "无画面";
      }
      inflight.delete(id);
    };
    probe.src = "/browsers/" + id + "/screenshot?t=" + Date.now();
  });
}

export function stopBrowserShots() {
  if (shotTimer) {
    clearInterval(shotTimer);
    shotTimer = 0;
  }
  inflight.clear();
}

export function startBrowserShots(opts = {}) {
  loadShotInterval();
  if (opts.restart || !shotTimer) {
    stopBrowserShots();
    tickBrowserShots();
    shotTimer = setInterval(tickBrowserShots, Math.round(shotInterval() * 1000));
    return;
  }
  tickBrowserShots({ onlyEmpty: true });
}

export function onShotIntervalChange(ev) {
  const el = ev.target.closest("[data-shot-interval]");
  if (!el) return false;
  const n = saveShotInterval(el.value);
  el.value = String(n);
  startBrowserShots({ restart: true });
  return true;
}

export function onBrowsersAction(ev) {
  const start = ev.target.closest("[data-browser-start]");
  if (start) {
    if (start.disabled) return Promise.resolve(false);
    start.disabled = true;
    return postJSON("/browsers", {}).then(() => {
      state.error = "";
      return true;
    }).catch((err) => {
      state.error = String(err.message || err);
      return true;
    });
  }
  const close = ev.target.closest("[data-browser-close]");
  if (close) {
    if (close.disabled) return Promise.resolve(false);
    const id = Number(close.getAttribute("data-browser-close"));
    if (!Number.isFinite(id) || id < 1) return Promise.resolve(false);
    close.disabled = true;
    return postJSON("/browsers/" + id + "/status", { status: "closed" }).then(() => {
      state.error = "";
      return true;
    }).catch((err) => {
      state.error = String(err.message || err);
      return true;
    });
  }
  const power = ev.target.closest("[data-browser-power]");
  if (power) {
    if (power.disabled) return Promise.resolve(false);
    const id = Number(power.getAttribute("data-browser-power"));
    if (!Number.isFinite(id) || id < 1) return Promise.resolve(false);
    power.disabled = true;
    return postJSON("/browsers/" + id + "/power-on", {}).then(() => {
      state.error = "";
      return true;
    }).catch((err) => {
      state.error = String(err.message || err);
      return true;
    });
  }
  const del = ev.target.closest("[data-browser-delete]");
  if (!del) return Promise.resolve(false);
  if (del.disabled) return Promise.resolve(false);
  const delId = Number(del.getAttribute("data-browser-delete"));
  if (!Number.isFinite(delId) || delId < 1) return Promise.resolve(false);
  del.disabled = true;
  return delJSON("/browsers/" + delId).then(() => {
    state.error = "";
    return true;
  }).catch((err) => {
    state.error = String(err.message || err);
    return true;
  });
}
