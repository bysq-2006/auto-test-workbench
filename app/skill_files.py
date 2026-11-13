"""扫描 skills/ 目录。只读文件内容，不执行脚本，也不写数据库。"""

import ast
from pathlib import Path

from app.db import ROOT, SKILLS_DIR


def _docstring(source: str) -> str:
    try:
        doc = ast.get_docstring(ast.parse(source))
    except SyntaxError:
        return ""
    return (doc or "").strip()


def _skill_meta(source: str) -> dict | None:
    """如果文件里写了 SKILL = {...} 或 SKILL: dict = {...}，取出 name / description。"""
    try:
        tree = ast.parse(source)
    except SyntaxError:
        return None
    for node in tree.body:
        if isinstance(node, ast.Assign):
            names = [target.id for target in node.targets if isinstance(target, ast.Name)]
            value_node = node.value
        elif isinstance(node, ast.AnnAssign):
            # 带类型注解的赋值是 AnnAssign，不是 Assign；只有注解没赋值时 value 是 None
            if node.value is None:
                continue
            names = [node.target.id] if isinstance(node.target, ast.Name) else []
            value_node = node.value
        else:
            continue
        if "SKILL" not in names:
            continue
        try:
            value = ast.literal_eval(value_node)
        except (ValueError, TypeError):
            return None
        if isinstance(value, dict):
            return value
    return None


def read_skill(path: Path) -> dict:
    rel = path.relative_to(ROOT).as_posix()
    try:
        source = path.read_text(encoding="utf-8")
    except OSError:
        source = ""
    meta = _skill_meta(source) or {}
    name = str(meta.get("name") or path.stem).strip() or path.stem
    if meta.get("description") is not None:
        description = str(meta.get("description")).strip()
    else:
        description = _docstring(source)
    return {"name": name, "description": description, "path": rel}


def scan_skills() -> list[dict]:
    """扫描 skills/*.py，介绍来自文件内部的 SKILL 字典或模块文档字符串。"""
    items = []
    if not SKILLS_DIR.is_dir():
        return items
    for path in sorted(SKILLS_DIR.glob("*.py")):
        if path.name.startswith("_"):
            continue
        items.append(read_skill(path))
    return items


def resolve_skill(ref: str | None) -> dict | None:
    """按路径、文件名或 SKILL 里的名字找到一个技能。"""
    if not ref or not str(ref).strip():
        return None
    key = str(ref).strip().replace("\\", "/")
    for item in scan_skills():
        path = item["path"]
        if key in {path, Path(path).name, Path(path).stem, item["name"]}:
            return item
    return None


def skill_fields(path: str | None) -> dict:
    """给任务/结果补上 skill_name；文件已经不在时，名字就用路径里的文件名。"""
    if not path:
        return {"skill_path": None, "skill_name": None}
    skill = resolve_skill(path)
    if skill:
        return {"skill_path": skill["path"], "skill_name": skill["name"]}
    return {"skill_path": path, "skill_name": Path(path).stem}
