/** 前端会话数据。轮询只改这里，各列表页码、搜索和筛选单独留着。 */

export const state = {
  status: { results: { pass: 0, fail: 0 } },
  /** 轮次列表和当前选中的那一轮。选中值只是给界面筛数据用，AI 的归属不读它。 */
  rounds: [],
  roundsUnassigned: { tasks: 0, results: 0, messages: 0 },
  round: null,
  roundMenuOpen: false,
  roundQuery: "",
  /** 下拉里正在填的表单：null | { mode: "new" | "close", force: boolean, id: number|null } */
  roundDialog: null,
  /** 行内「…」弹窗开在哪一轮：null 或轮次编号 */
  roundOps: null,
  tasks: [],
  tasksTotal: 0,
  skills: [],
  skillsTotal: 0,
  results: [],
  resultsTotal: 0,
  messages: [],
  messagesTotal: 0,
  browsers: [],
  browsersTotal: 0,
  listPage: { tasks: 1, skills: 1, results: 1, messages: 1, browsers: 1 },
  listQuery: { tasks: "", skills: "", results: "", messages: "", browsers: "" },
  listFilter: {
    tasks: { status: "" },
    results: { kind: "", recorded: "" },
    browsers: { status: "" },
  },
  expanded: {},
  error: "",
};

/** 各列表每页条数。 */
export const LIST_PAGE_SIZE = 10;
