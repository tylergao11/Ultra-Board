import json
from pathlib import Path

ROOT = Path("data/kaipanla/raw")
days = sorted(p.name for p in ROOT.iterdir() if (p / "zt_pool.json").exists())


def load(d):
    return json.loads((ROOT / d / "zt_pool.json").read_text(encoding="utf-8"))


def find(d, code):
    for s in load(d)["stocks"]:
        if str(s.get("code")).zfill(6) == code:
            return s
    return None


# walk 腾达 streak back from 7.29
code = "001379"
print("腾达连板回溯")
for d in days:
    if d > "2024-08-06":
        break
    if d < "2024-07-15":
        continue
    s = find(d, code)
    if s:
        raw = s.get("raw") or []
        print(d, f"{s['boards']}板 价{s['price']} 换手{s['turnover_rate']} raw13={raw[13] if len(raw)>13 else None} raw6={raw[6] if len(raw)>6 else None}")
