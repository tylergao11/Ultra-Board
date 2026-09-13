import json
from datetime import datetime, timezone, timedelta
from pathlib import Path

TZ = timezone(timedelta(hours=8))
ROOT = Path("data/kaipanla/raw")
days = sorted(p.name for p in ROOT.iterdir() if (p / "zt_pool.json").exists())
obs = "2024-07-29"
prev = days[days.index(obs) - 1]


def load(d):
    return json.loads((ROOT / d / "zt_pool.json").read_text(encoding="utf-8"))


def hhmm(ts):
    return datetime.fromtimestamp(int(ts), TZ).strftime("%H:%M") if ts else "-"


def dump(d, sec="801843"):
    data = load(d)
    rows = [s for s in data["stocks"] if (s.get("sector_code") or "") == sec or (s.get("theme") or "") == "商业航天"]
    print(f"{d} 全场{data['count']} H={data['max_board']}  商业航天/801843 {len([s for s in data['stocks'] if s.get('sector_code')==sec])}家")
    for s in rows:
        print(f"  {s['name']} {s['boards']}板 换手{s['turnover_rate']} 首封{hhmm(s.get('first_limit_ts'))} theme={s.get('theme')} code={s.get('sector_code')}")


print("观察日", obs, "前一日", prev)
dump(prev)
dump(obs)
t = next(s for s in load(obs)["stocks"] if s["code"] == "001379")
print("腾达", t["boards"], "板", t["theme"], t["sector_code"], "换手", t["turnover_rate"], "首封", hhmm(t.get("first_limit_ts")))
