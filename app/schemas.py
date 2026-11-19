"""接口入参。"""

from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator


def _accept_skill(data):
    """skill_path 当成 skill。skill_id 已经不用了，传了就直接报错。"""
    if isinstance(data, dict) and not data.get("skill"):
        if data.get("skill_path"):
            return {**data, "skill": data["skill_path"]}
        if data.get("skill_id") is not None:
            raise ValueError("技能请传 skill（文件路径或文件名），不再使用 skill_id")
    return data


class RoundIn(BaseModel):
    """开一轮。name 例：崇州-26.11.18。"""

    name: str = Field(min_length=1)
    note: str = ""


class RoundCloseIn(BaseModel):
    """关轮时必须写一句结论；还有任务没跑完要带 force。"""

    note: str = Field(min_length=1)
    force: bool = False


class TaskIn(BaseModel):
    title: str = Field(min_length=1)
    description: str = ""
    skill: str | None = None
    payload: Any = None
    round_id: int | None = None

    @model_validator(mode="before")
    @classmethod
    def accept_skill_path(cls, data):
        return _accept_skill(data)


class TaskClaimIn(BaseModel):
    agent_name: str = Field(min_length=1)


class TaskStatusIn(BaseModel):
    status: Literal["pending", "running", "done", "failed"]
    agent_name: str | None = None


class ResultIn(BaseModel):
    agent_name: str = Field(min_length=1)
    kind: Literal["test", "note"] = "test"
    task_id: int | None = None
    skill: str | None = None
    status: Literal["pass", "fail"] | None = None
    summary: str = ""
    log_text: str = ""
    # 挂了 task_id 时可以不传，服务端从任务抄过来；两条都传且不一致返回 400
    round_id: int | None = None

    @model_validator(mode="before")
    @classmethod
    def accept_skill_path(cls, data):
        return _accept_skill(data)

    @model_validator(mode="after")
    def status_matches_kind(self):
        # 普通记录不需要通过/失败；测试则必须带上
        if self.kind == "note":
            return self.model_copy(update={"status": None})
        if self.status not in ("pass", "fail"):
            raise ValueError("测试结果必须带 status（pass 或 fail）")
        return self


class MessageIn(BaseModel):
    name: str = ""
    body: str = Field(min_length=1)
    round_id: int | None = None

    @model_validator(mode="before")
    @classmethod
    def accept_from_agent(cls, data):
        # 兼容旧字段 from_agent，当成名字用
        if isinstance(data, dict):
            name = data.get("name")
            if (name is None or not str(name).strip()) and data.get("from_agent"):
                data = {**data, "name": data["from_agent"]}
        return data


class ResultRecordedIn(BaseModel):
    recorded: bool


class BrowserCreateIn(BaseModel):
    """启动浏览器。请求体不要带 port，端口由服务端分配。name 可空。"""

    model_config = ConfigDict(extra="allow")
    name: str = ""


class BrowserNameIn(BaseModel):
    """改这台浏览器的名称。空字符串表示没有名称。"""

    name: str = ""


class BrowserStatusIn(BaseModel):
    status: Literal["idle", "occupied", "closed"]
    agent_name: str | None = None


