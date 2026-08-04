# -*- coding: utf-8 -*-
"""Gate: scripts 下不得出现其它机器绝对盘符数据根（拼出模式，避免自检命中）。"""
from __future__ import annotations

import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent
# 拼出禁止串，避免本文件被自身规则命中
_FORBIDDEN = re.compile(
    re.escape("D:" + "\\" + "Ultra-Board")
    + "|"
    + re.escape("D:" + "/" + "Ultra-Board")
)


def main() -> int:
    paths = list(ROOT.rglob("*.py"))
    bad: list[str] = []
    for p in paths:
        if p.resolve() == Path(__file__).resolve():
            continue
        for line in p.read_text(encoding="utf-8", errors="ignore").splitlines():
            if _FORBIDDEN.search(line):
                bad.append(str(p))
                break
    if bad:
        print("hardcoded_roots:", bad, file=sys.stderr)
        return 1
    print("no_hardcoded_D_drive", len(paths))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
