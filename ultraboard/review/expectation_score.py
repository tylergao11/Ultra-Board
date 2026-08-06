# -*- coding: utf-8 -*-
"""节点日预期评分命令入口。

算法唯一实现仍在 ``candidate_initial_score``，本模块只提供语义清晰的命令名，
避免产生第二套权重或评分真相。
"""
from __future__ import annotations

import sys

from ultraboard.review.candidate_initial_score import main


if __name__ == "__main__":
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    raise SystemExit(main())
