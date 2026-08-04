# -*- coding: utf-8 -*-
import json
from pathlib import Path

RAW = Path(__file__).resolve().parents[2] / "data" / "kaipanla" / "raw"

for name in ("大有能源", "华远控股", "盈新发展", "锋龙股份"):
    print("====", name)
    for p in sorted(RAW.iterdir()):
        f = p / "zt_pool.json"
        if not f.exists():
            continue
        zt = json.loads(f.read_text(encoding="utf-8-sig"))
        for s in zt["stocks"]:
            if s["name"] != name:
                continue
            print(
                p.name,
                f"{s['boards']}板",
                "theme=",
                repr(s.get("theme")),
            )
    print()
