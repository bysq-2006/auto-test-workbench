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
