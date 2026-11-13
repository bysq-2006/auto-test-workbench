"""技能：每次请求都扫描 skills/ 目录，不走数据库。"""

from fastapi import APIRouter, Query

from app.skill_files import scan_skills

router = APIRouter()


@router.get("/skills")
def list_skills(
    q: str | None = Query(None),
    limit: int = Query(10, ge=1, le=200),
    page: int = Query(1, ge=1),
):
    """扫描后可按关键字筛，再按页返回。"""
    items = scan_skills()
    if q and q.strip():
        key = q.strip().lower()
        items = [
            item for item in items
            if key in " ".join([item.get("name") or "", item.get("path") or "", item.get("description") or ""]).lower()
        ]
    total = len(items)
    start = (page - 1) * limit
    return {
        "items": items[start:start + limit],
        "total": total,
        "page": page,
        "limit": limit,
    }
