import json
from datetime import datetime, timezone, timedelta
from pathlib import Path

TZ = timezone(timedelta(hours=8))
day = "2024-10-29"
data = json.loads(Path(f"data/kaipanla/raw/{day}/zt_pool.json").read_text(encoding="utf-8"))
print("低空 801829 on", day)
for s in data["stocks"]:
    if s.get("sector_code") == "801829" or "低空" in (s.get("theme") or ""):
        ts = datetime.fromtimestamp(int(s["first_limit_ts"]), TZ).strftime("%H:%M") if s.get("first_limit_ts") else "-"
        print(s["name"], s["code"], s["boards"], "换手", s["turnover_rate"], "首封", ts, s["theme"], s.get("sector_code"))

print("\n亚泰 sector across days")
for d in ["2024-09-23", "2024-09-24", "2024-09-25", "2024-09-26"]:
    data = json.loads(Path(f"data/kaipanla/raw/{d}/zt_pool.json").read_text(encoding="utf-8"))
    s = next(x for x in data["stocks"] if x["code"] == "600881")
    print(d, s["theme"], s.get("sector_code"), "同code数", sum(1 for x in data["stocks"] if x.get("sector_code")==s.get("sector_code")))
    print("  801676", sum(1 for x in data["stocks"] if x.get("sector_code")=="801676"),
          "801007", sum(1 for x in data["stocks"] if x.get("sector_code")=="801007"))
