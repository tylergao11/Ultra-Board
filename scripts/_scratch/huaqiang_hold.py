import json
from datetime import datetime, timezone, timedelta
from pathlib import Path

TZ = timezone(timedelta(hours=8))
ROOT = Path("data/kaipanla/raw")
SEC = "801359"
KEY = "华为海思"
CODE = "000062"


def load(d):
    return json.loads((ROOT / d / "zt_pool.json").read_text(encoding="utf-8"))


def hhmm(ts):
    return datetime.fromtimestamp(int(ts), TZ).strftime("%H:%M") if ts else "-"


def hit(s):
    return KEY in ((s.get("theme") or "") + "|" + (s.get("theme_tags_text") or "")) or (s.get("sector_code") or "") == SEC


for d in ["2024-08-19", "2024-08-20", "2024-08-21", "2024-08-22", "2024-08-23",
          "2024-08-26", "2024-08-27", "2024-08-28", "2024-08-29"]:
    data = load(d)
    main = [s for s in data["stocks"] if (s.get("sector_code") or "") == SEC]
    attr = [s for s in data["stocks"] if hit(s)]
    t = next((s for s in data["stocks"] if s["code"] == CODE), None)
    print(f"\n==== {d} 全场{data['count']} H={data['max_board']}  主海思{len(main)} 属海思{len(attr)} ====")
    if t:
        print(
            f"华强 {t['boards']}板 换手{t['turnover_rate']} 额{t.get('amount')} "
            f"首封{hhmm(t.get('first_limit_ts'))} 价{t.get('price')}"
        )
    else:
        print("华强 不在涨停池")
    for s in sorted(main, key=lambda x: -(x.get("boards") or 0)):
        print(f"  {s['name']} {s['boards']}板 换手{s['turnover_rate']} 首封{hhmm(s.get('first_limit_ts'))}")
    extra = [s for s in attr if (s.get("sector_code") or "") != SEC]
    for s in extra:
        print(f"  +属 {s['name']} {s['boards']}板 theme={s.get('theme')} tags={s.get('theme_tags_text')}")
