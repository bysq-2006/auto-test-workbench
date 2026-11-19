/** hash 路由。侧栏七项。 */

export const PAGES = {
  dashboard: "仪表盘",
  skills: "技能",
  tasks: "任务",
  results: "结果",
  browsers: "资源",
  messages: "消息",
  docs: "使用说明",
};

/** hash 第一段是页面。不认识的路径回到仪表盘。 */
export function pageId() {
  const raw = (location.hash || "#/dashboard").replace("#/", "").split("/")[0].split("?")[0];
  return PAGES[raw] ? raw : "dashboard";
}

/** hash 里的 round 参数，例：#/tasks?round=12。没带就是空字符串。 */
export function roundParam() {
  const query = (location.hash || "").split("?")[1] || "";
  return new URLSearchParams(query).get("round") || "";
}

/** 改 hash 里的 round，保留当前页面。值没变则返回 false，调用方自己决定要不要重绘。 */
export function setRoundParam(value) {
  const [path, query] = (location.hash || "#/dashboard").split("?");
  const params = new URLSearchParams(query || "");
  if (value == null || value === "") params.delete("round");
  else params.set("round", String(value));
  const rest = params.toString();
  const next = path + (rest ? "?" + rest : "");
  if (next === location.hash) return false;
  location.hash = next;
  return true;
}
