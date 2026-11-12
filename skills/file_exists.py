"""检查路径是否存在。

用法: python skills/file_exists.py <路径>
路径存在时退出码为 0，否则为 1。
"""

import sys
from pathlib import Path


def main() -> int:
    if len(sys.argv) != 2:
        print("用法: python skills/file_exists.py <路径>", file=sys.stderr)
        return 2
    path = Path(sys.argv[1])
    if path.exists():
        print(f"exists {path}")
        return 0
    print(f"missing {path}")
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
