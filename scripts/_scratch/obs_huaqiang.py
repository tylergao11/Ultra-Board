import json
from datetime import datetime, timezone, timedelta
from pathlib import Path

TZ = timezone(timedelta(hours=8))
ROOT = Path("data/kaipanla/raw")
days = sorted(p.name for p in ROOT.iterdir() if (p / "zt_pool.json").exists())
obs = "2024-08-19"
prev = days[days.index(obs) - 1]
KEY = "华为海思"


def load(d):
    return json.loads((ROOT / d / "zt_pool.json").read_text(encoding="utf-8"))


def hhmm(ts):
    return datetime.fromtimestamp(int(ts), TZ).strftime("%H:%M") if ts else "-"


def dump(d):
    data = load(d)
    hq = next((s for s in data["stocks"] if s["code"] == "000062"), None)
    print(f"\n==== {d} 全场{data['count']} H={data['max_board']} ====")
    if hq:
        print(
            f"华强 {hq['boards']}板 换手{hq['turnover_rate']} 首封{hhmm(hq.get('first_limit_ts'))} "
            f"theme={hq.get('theme')} sec={hq.get('sector_code')} tags={hq.get('theme_tags_text')} "
            f"价{hq.get('price')} raw13={hq.get('raw',[0]*14)[13] if hq.get('raw') else None}"
        )
    else:
        print("华强 不在池")

    # theme frequency
    themes = {}
    for s in data["stocks"]:
        t = s.get("theme") or "?"
        themes[t] = themes.get(t, 0) + 1
    print("theme top:", ", ".join(f"{k}:{v}" for k, v in sorted(themes.items(), key=lambda x: -x[1])[:15]))

    sec = hq.get("sector_code") if hq else ""
    print(f"\n主标签 theme=={hq.get('theme') if hq else KEY} 或 sector={sec}")
    main = [s for s in data["stocks"] if (s.get("theme") == (hq.get("theme") if hq else KEY)) or (sec and s.get("sector_code") == sec)]
    # split
    by_theme = [s for s in data["stocks"] if (s.get("theme") or "") == (hq.get("theme") if hq else KEY)]
    by_sec = [s for s in data["stocks"] if sec and (s.get("sector_code") or "") == sec]
    print(f"  同theme {len(by_theme)}  同sector_code {len(by_sec)}")
    for s in by_theme:
        print(f"    [theme] {s['name']} {s['boards']}板 换手{s['turnover_rate']} 首封{hhmm(s.get('first_limit_ts'))} sec={s.get('sector_code')} tags={s.get('theme_tags_text')}")
    extra_sec = [s for s in by_sec if (s.get("theme") or "") != (hq.get("theme") if hq else KEY)]
    for s in extra_sec:
        print(f"    [sec不同theme] {s['name']} {s['boards']}板 theme={s.get('theme')} sec={s.get('sector_code')}")

    print(f"\n属性含「{KEY}」")
    attr = []
    for s in data["stocks"]:
        blob = (s.get("theme") or "") + "|" + (s.get("theme_tags_text") or "")
        if KEY in blob:
            attr.append(s)
    print(f"  {len(attr)}家")
    for s in attr:
        mark = "主" if (s.get("theme") or "") == KEY or (sec and s.get("sector_code") == sec) else "挂"
        print(f"    [{mark}] {s['name']} {s['boards']}板 theme={s.get('theme')} tags={s.get('theme_tags_text')} sec={s.get('sector_code')}")

    # also 华为 without 海思
    huawei = [s for s in data["stocks"] if "华为" in ((s.get("theme") or "") + "|" + (s.get("theme_tags_text") or ""))]
    print(f"\n属性含「华为」{len(huawei)}家: " + ", ".join(f"{s['name']}/{s.get('theme')}" for s in huawei))


print("观察日", obs, "前一日", prev)
dump(prev)
dump(obs)
