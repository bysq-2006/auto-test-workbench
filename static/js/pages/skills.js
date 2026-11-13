/** 技能列表。数据来自 GET /skills，后端扫描文件，不读数据库。 */

import { renderList } from "../list.js";
import { state } from "../state.js";
import { empty, esc, clipCell } from "../util.js";

export function skillRows(items, limit) {
  const rows = items.slice(0, limit || items.length);
  if (!rows.length) return empty("暂无技能");
  return `<table>
    <thead><tr><th>名称</th><th>路径</th><th>介绍</th></tr></thead>
    <tbody>${rows.map((skill) => `<tr>
      <td>${esc(skill.name)}</td>
      <td><code>${esc(skill.path)}</code></td>
      ${clipCell("skills", skill.path || skill.name, "description", skill.description)}
    </tr>`).join("")}</tbody>
  </table>`;
}

function skillsToolbar() {
  const q = state.listQuery.skills || "";
  return `<div class="list-toolbar">
    <input id="filter-skills-q" data-search-kind="skills" type="search" placeholder="搜索名称、路径或介绍" value="${esc(q)}">
  </div>`;
}

export function renderSkills() {
  const body = state.skills.length ? skillRows(state.skills) : "";
  return renderList({
    kind: "skills",
    title: "技能",
    emptyText: "暂无技能",
    toolbar: skillsToolbar(),
    body,
    total: state.skillsTotal,
  });
}
