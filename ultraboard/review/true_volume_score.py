# -*- coding: utf-8 -*-
"""旧命令兼容入口；唯一实现已迁至 ``exchange_tags``。

该入口不再输出真实爆量总分。新调用请使用：

  python -m ultraboard.review.exchange_tags DATE
"""
from __future__ import annotations

import sys

from ultraboard.review.exchange_tags import (
    analyze_day,
    analyze_stock,
    main,
    markdown_report,
)

__all__ = ["analyze_day", "analyze_stock", "markdown_report", "main"]


if __name__ == "__main__":
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    raise SystemExit(main())
