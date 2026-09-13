import json
from datetime import datetime, timezone, timedelta
from pathlib import Path

TZ = timezone(timedelta(hours=8))
ROOT = Path("data/kaipanla/raw")


def load(d):
    return json.loads((ROOT / d / "zt_pool.json").read_text(encoding="utf-8"))


def hhmm(ts):
    return datetime.fromtimestamp(int(ts), TZ).strftime("%H:%M") if ts else "-"


def dump_code(d, codes):
    data = load(d)
    print(f"\n==== {d} 全场{data['count']} H={data['max_board']} ====")
    for code in codes:
        s = next((x for x in data["stocks"] if str(x.get("code")).zfill(6) == code), None)
        if not s:
            print(f"  {code} 不在池")
            continue
        blob = (s.get("theme") or "") + "|" + (s.get("theme_tags_text") or "")
        print(
            f"  {s['name']} {s['boards']}板 换手{s['turnover_rate']} 首封{hhmm(s.get('first_limit_ts'))} "
            f"theme={s.get('theme')} sec={s.get('sector_code')} tags={s.get('theme_tags_text')} "
            f"含华为={'Y' if '华为' in blob else 'N'}"
        )


def dump_attr(d, key):
    data = load(d)
    rows = []
    for s in data["stocks"]:
        blob = (s.get("theme") or "") + "|" + (s.get("theme_tags_text") or "")
        if key in blob:
            rows.append(s)
    print(f"  属性含「{key}」{len(rows)}: " + ", ".join(f"{s['name']}{s['boards']}/{s.get('theme')}" for s in rows))


codes = ["002514", "603626", "000062"]
for d in ["2024-08-27", "2024-08-28", "2024-08-29", "2024-08-30",
          "2024-09-02", "2024-09-03", "2024-09-04"]:
    dump_code(d, codes)
    dump_attr(d, "华为")
    dump_attr(d, "电子烟")
    dump_attr(d, "消费电子")
