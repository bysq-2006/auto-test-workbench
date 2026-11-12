# 多智能体测试工作台

本地小服务，给主代理和子代理共用。内容包括技能说明、待办队列、测试结果，以及代理之间的消息和资源占用。数据在 SQLite 文件 `data/workbench.db`，没有登录鉴权，只适合本机使用。

## 安装和运行

需要 Python 3.10 或更高版本。如果系统里的 `python` 还是 3.7，用已安装的 3.10 解释器创建虚拟环境。本机可以用 `C:\Users\19045\anaconda3\envs\teacher\python.exe`。

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt
uvicorn app.main:app --host 127.0.0.1 --port 8000
```

浏览器打开 http://127.0.0.1:8000 。页面每 3 秒刷新任务数量，并用 Chart.js（CDN）画一张状态柱状图。

启动时会扫描 `skills/*.py`，把文件名、顶部说明和相对路径写入 `skills` 表。

## 接口

| 方法 | 路径 | 作用 |
| --- | --- | --- |
| GET | `/skills` | 列出技能和脚本路径 |
| GET | `/tasks?status=pending` | 任务列表，可按状态过滤 |
| POST | `/tasks` | 新建任务，状态为 `pending` |
| POST | `/tasks/{id}/claim` | 认领待办，状态变为 `running` |
| POST | `/tasks/{id}/status` | 把状态改为 `pending` / `running` / `done` / `failed` |
| GET | `/test-results` | 测试结果列表 |
| POST | `/test-results` | 写入一条通过或失败 |
| GET | `/messages` | 普通消息，`to_agent` 为空表示广播 |
| POST | `/messages` | 发消息 |
| GET | `/claims?status=held` | 查看资源占用 |
| POST | `/claims` | 占用资源；已被别人占用时返回 409 |
| POST | `/claims/release` | 释放自己占用的资源 |
| GET | `/api/status` | 仪表盘数字：任务数、通过/失败、占用数 |

创建任务的 JSON 示例：

```json
{"title": "检查示例文件", "skill_id": 1, "payload": {"path": "README.md"}}
```

认领：`{"assignee": "main"}`。占用资源：`{"resource": "device-1", "owner": "tester-a"}`。

## 协作约定

子代理用 `POST /tasks` 放入待办。主代理用 `POST /tasks/{id}/claim` 按 `pending` 认领，做完后把状态改成 `done` 或 `failed`。

测试子代理每跑完一次，用 `POST /test-results` 记一条，`status` 为 `pass` 或 `fail`。

动手使用共享资源之前先查 `GET /claims?resource=名字&status=held`。没有记录再 `POST /claims`。若返回 409，说明别人占着，不要抢。用完调用 `POST /claims/release`。

## 示例技能

- `skills/echo_check.py`：打印参数并成功退出
- `skills/file_exists.py`：检查路径是否存在
- `skills/json_has_key.py`：检查 JSON 顶层是否有某个键
