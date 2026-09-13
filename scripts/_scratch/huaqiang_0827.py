import json
from datetime import datetime, timezone, timedelta
from pathlib import Path

TZ = timezone(timedelta(hours=8))
ROOT = Path("data/kaipanla/raw")


def load(d):
    return json.loads((ROOT / d / "zt_pool.json").read_text(encoding="utf-8"))


def hhmm(ts):
    return datetime.fromtimestamp(int(ts), TZ).strftime("%H:%M") if ts else "-"


def blob(s):
    return (s.get("theme") or "") + "|" + (s.get("theme_tags_text") or "")


for d in ["2024-08-26", "2024-08-27"]:
    data = load(d)
    print(f"\n==== {d} 全场{data['count']} H={data['max_board']} ====")
    for key in ("华为海思", "华为概念", "华为", "消费电子"):
        rows = [s for s in data["stocks"] if key in blob(s) or (s.get("theme") or "") == key]
        # unique by code
        seen = {}
        for s in rows:
            seen[s["code"]] = s
        rows = list(seen.values())
        print(f"  含{key} {len(rows)}")
        for s in sorted(rows, key=lambda x: -(x.get("boards") or 0)):
            print(
                f"    {s['name']} {s['boards']}板 换手{s['turnover_rate']} 首封{hhmm(s.get('first_limit_ts'))} "
                f"theme={s.get('theme')} tags={s.get('theme_tags_text')}"
            )
    # 共进
    gj = next((s for s in data["stocks"] if s["code"] == "603118"), None)
    print("  共进", f"{gj['boards']}板" if gj else "不在池")
