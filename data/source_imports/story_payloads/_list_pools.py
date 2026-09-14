# -*- coding: utf-8 -*-
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
for day in [
    "2026-02-11",
    "2026-02-12",
    "2026-02-13",
    "2026-02-24",
    "2026-02-25",
    "2026-02-26",
    "2026-02-27",
]:
    data = json.loads(
        (ROOT / f"data/ths/limit_pool/{day}.json").read_text(encoding="utf-8-sig")
    )
    rows = data.get("stocks") or []
    print(day, "n=", len(rows))
    for r in rows:
        print(f"  {r.get('code')}:{r.get('name')}")
    print()
