"""打印参数并成功退出，用来确认技能脚本能被调用。

用法: python skills/echo_check.py [消息]
"""

import sys


def main() -> int:
    text = " ".join(sys.argv[1:]).strip() or "ok"
    print(text)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
