import json
from datetime import datetime, timezone, timedelta
from pathlib import Path

TZ = timezone(timedelta(hours=8))
ROOT = Path("data/kaipanla/raw")
SEC = "801328"
KEY = "消费电子"


def load(d):
    return json.loads((ROOT / d / "zt_pool.json").read_text(encoding="utf-8"))


def hhmm(ts):
    return datetime.fromtimestamp(int(ts), TZ).strftime("%H:%M") if ts else "-"


for d in ["2024-08-28", "2024-08-29", "2024-08-30", "2024-09-02", "2024-09-03"]:
    data = load(d)
    main = [s for s in data["stocks"] if (s.get("theme") or "") == KEY or (s.get("sector_code") or "") == SEC]
    by_theme = [s for s in data["stocks"] if (s.get("theme") or "") == KEY]
    by_sec = [s for s in data["stocks"] if (s.get("sector_code") or "") == SEC]
    attr = [s for s in data["stocks"] if KEY in ((s.get("theme") or "") + "|" + (s.get("theme_tags_text") or ""))]
    k = next((s for s in data["stocks"] if s["code"] == "603626"), None)
    print(f"\n==== {d} 全场{data['count']} H={data['max_board']}  主theme{len(by_theme)} 主sec{len(by_sec)} 属{len(attr)} ====")
    if k:
        print(
            f"科森 {k['boards']}板 换手{k['turnover_rate']} 首封{hhmm(k.get('first_limit_ts'))} "
            f"theme={k.get('theme')} sec={k.get('sector_code')} tags={k.get('theme_tags_text')}"
        )
    else:
        print("科森 不在池")
    print("主theme消费电子:")
    for s in sorted(by_theme, key=lambda x: -(x.get("boards") or 0)):
        print(f"  {s['name']} {s['boards']}板 换手{s['turnover_rate']} 首封{hhmm(s.get('first_limit_ts'))} tags={s.get('theme_tags_text')}")
    extra = [s for s in attr if (s.get("theme") or "") != KEY]
    if extra:
        print("属性有消费电子但主标签不是:")
        for s in extra:
            print(f"  {s['name']} {s['boards']}板 theme={s.get('theme')} tags={s.get('theme_tags_text')}")
