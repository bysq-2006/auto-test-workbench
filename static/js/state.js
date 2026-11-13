/** 前端会话数据。轮询只改这里，各列表页码、搜索和筛选单独留着。 */

export const state = {
  status: { results: { pass: 0, fail: 0 } },
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
