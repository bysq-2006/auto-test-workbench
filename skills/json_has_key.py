"""检查 JSON 文件的顶层对象是否包含指定键。

用法: python skills/json_has_key.py <json文件> <键名>
找到键时退出码为 0，否则为 1。
"""

import json
import sys
from pathlib import Path


def main() -> int:
    if len(sys.argv) != 3:
        print("用法: python skills/json_has_key.py <json文件> <键名>", file=sys.stderr)
        return 2
    path, key = sys.argv[1], sys.argv[2]
    data = json.loads(Path(path).read_text(encoding="utf-8"))
    if not isinstance(data, dict):
        print("顶层必须是 JSON 对象", file=sys.stderr)
        return 1
    if key not in data:
        print(f"缺少键: {key}")
        return 1
    print(f"ok {key}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
