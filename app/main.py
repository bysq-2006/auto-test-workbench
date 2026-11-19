"""多智能体测试工作台入口：启动、静态页，再挂上各模块路由。"""

from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from app.db import ROOT, init_db, locked_connect
from app.deps import UTF8JSONResponse
from app.routers import browsers, messages, results, rounds, skills, status, tasks

STATIC = ROOT / "static"


class NoCacheStaticFiles(StaticFiles):
    """本地工作台：静态文件每次让浏览器回源确认，改完刷新就能看到。

    多模块的 import 没有版本号，只给 main.js 加 ?v= 管不住被缓存的子模块。
    用 no-cache（仍带 ETag，没变就是 304）比 no-store 省事，也不会残留下线文件。
    """

    async def get_response(self, path: str, scope):
        response = await super().get_response(path, scope)
        response.headers["Cache-Control"] = "no-cache"
        return response


@asynccontextmanager
async def lifespan(_app: FastAPI):
    # 启动时建表或升级旧库；技能不再同步进数据库
    with locked_connect() as conn:
        init_db(conn)
    yield


app = FastAPI(
    title="Auto Test Workbench",
    default_response_class=UTF8JSONResponse,
    lifespan=lifespan,
)
app.mount("/static", NoCacheStaticFiles(directory=STATIC), name="static")

app.include_router(skills.router)
app.include_router(rounds.router)
app.include_router(results.router)
app.include_router(messages.router)
app.include_router(tasks.router)
app.include_router(browsers.router)
app.include_router(status.router)


@app.get("/")
def index():
    return FileResponse(STATIC / "index.html")
