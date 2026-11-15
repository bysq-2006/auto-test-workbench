/** 使用说明：工作台侧栏之外再加一组文档导航，右侧是文章。 */

import { esc } from "./util.js";

export const DOCS = {
  testing: {
    label: "测试",
    items: [
      { id: "skills", label: "技能" },
      { id: "nav", label: "导航" },
      { id: "tasks", label: "任务" },
      { id: "results", label: "结果" },
      { id: "browsers", label: "资源" },
    ],
  },
  chat: {
    label: "沟通",
    items: [
      { id: "messages", label: "消息" },
    ],
  },
};

const ARTICLE_IDS = Object.values(DOCS).flatMap((group) => group.items.map((item) => item.id));
const articles = new Map();
let ready = false;
let pending = null;

/** 从 hash 取出分组和篇目。缺了就落到该组第一篇。 */
export function docsRoute() {
  const parts = (location.hash || "").replace(/^#\//, "").split("/");
  let group = parts[1];
  let item = parts[2];
  if (!DOCS[group]) {
    group = "testing";
    item = "skills";
  } else if (!DOCS[group].items.some((entry) => entry.id === item)) {
    item = DOCS[group].items[0].id;
  }
  return { group, item };
}

export function docsCrumb() {
  const route = docsRoute();
  const group = DOCS[route.group];
  const item = group.items.find((entry) => entry.id === route.item);
  return `使用说明 / ${group.label} / ${item.label}`;
}

export function docsReady() {
  return ready;
}

/** 文案在 static/docs/articles，页面壳里不再放整篇说明。 */
export function loadArticles() {
  if (!pending) {
    pending = Promise.all(ARTICLE_IDS.map(async (id) => {
      const res = await fetch(`/static/docs/articles/${id}.html?v=41`);
      if (!res.ok) return;
      articles.set(id, await res.text());
    })).then(() => {
      ready = true;
    }).catch(() => {
      ready = true;
    });
  }
  return pending;
}

function articleBody(id) {
  if (!ready) return "";
  return articles.get(id) ?? "<p>还没有这篇说明。</p>";
}

export function renderDocs() {
  const route = docsRoute();
  const expected = `#/docs/${route.group}/${route.item}`;
  if (location.hash !== expected) {
    location.hash = expected;
    return "";
  }

  const nav = Object.entries(DOCS).map(([id, group]) => {
    const items = group.items.map((item) => (
      `<a href="#/docs/${id}/${item.id}" class="${id === route.group && item.id === route.item ? "active" : ""}">${esc(item.label)}</a>`
    )).join("");
    return `<div class="docs-group"><div class="docs-group-label">${esc(group.label)}</div>${items}</div>`;
  }).join("");

  return `<div class="docs-layout">
    <nav class="docs-nav">${nav}</nav>
    <article class="docs-article"><div class="doc-page">${articleBody(route.item)}</div></article>
  </div>`;
}
