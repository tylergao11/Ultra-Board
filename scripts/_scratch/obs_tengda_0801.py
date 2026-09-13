import json
from datetime import datetime, timezone, timedelta
from pathlib import Path

TZ = timezone(timedelta(hours=8))
ROOT = Path("data/kaipanla/raw")
KEY = "商业航天"
SEC = "801843"


def load(d):
    return json.loads((ROOT / d / "zt_pool.json").read_text(encoding="utf-8"))


def hhmm(ts):
    return datetime.fromtimestamp(int(ts), TZ).strftime("%H:%M") if ts else "-"


def hit(s):
    blob = (s.get("theme") or "") + "|" + (s.get("theme_tags_text") or "")
    return KEY in blob or (s.get("sector_code") or "") == SEC


def find(d, code="001379"):
    for s in load(d)["stocks"]:
        if str(s.get("code")).zfill(6) == code:
            return s
    return None


for d in ["2024-07-29", "2024-07-30", "2024-07-31", "2024-08-01"]:
    data = load(d)
    main = [s for s in data["stocks"] if (s.get("sector_code") or "") == SEC]
    attr = [s for s in data["stocks"] if hit(s)]
    t = find(d)
    print(f"\n==== {d} 全场涨停{data['count']} H={data['max_board']}  主标签航天{len(main)} 属性航天{len(attr)} ====")
    if t:
        print(
            f"腾达 {t['boards']}板 {t.get('boards_desc')} 换手{t['turnover_rate']} "
            f"额{t.get('amount')} 价{t.get('price')} 首封{hhmm(t.get('first_limit_ts'))} "
            f"theme={t.get('theme')} tags={t.get('theme_tags_text')}"
        )
    else:
        print("腾达 不在涨停池")
    print("主标签:")
    for s in sorted(main, key=lambda x: -(x.get("boards") or 0)):
        print(f"  {s['name']} {s['boards']}板 换手{s['turnover_rate']} 首封{hhmm(s.get('first_limit_ts'))} {s.get('theme')}")
    extra = [s for s in attr if (s.get("sector_code") or "") != SEC]
    if extra:
        print("属性多出来:")
        for s in extra:
            print(f"  {s['name']} {s['boards']}板 换手{s['turnover_rate']} theme={s.get('theme')} tags={s.get('theme_tags_text')}")
