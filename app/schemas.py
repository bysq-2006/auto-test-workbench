"""接口入参。"""

from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator


class TaskIn(BaseModel):
    title: str = Field(min_length=1)
    description: str = ""
    skill: str | None = None
    payload: Any = None

    @model_validator(mode="before")
    @classmethod
    def accept_skill_path(cls, data):
        if isinstance(data, dict) and not data.get("skill"):
            if data.get("skill_path"):
                data = {**data, "skill": data["skill_path"]}
            elif data.get("skill_id") is not None:
                raise ValueError("技能请传 skill（文件路径或文件名），不再使用 skill_id")
        return data


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

    @model_validator(mode="before")
    @classmethod
    def accept_skill_path(cls, data):
        if isinstance(data, dict) and not data.get("skill"):
            if data.get("skill_path"):
                data = {**data, "skill": data["skill_path"]}
            elif data.get("skill_id") is not None:
                raise ValueError("技能请传 skill（文件路径或文件名），不再使用 skill_id")
        return data

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
    """启动浏览器。请求体不要带 port，端口由服务端分配。"""

    model_config = ConfigDict(extra="allow")


class BrowserStatusIn(BaseModel):
    status: Literal["idle", "occupied", "closed"]
    agent_name: str | None = None


