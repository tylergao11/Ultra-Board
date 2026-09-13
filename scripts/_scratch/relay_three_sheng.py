import json
from pathlib import Path

ROOT = Path("data/kaipanla/raw")
days = sorted(p.name for p in ROOT.iterdir() if (p / "zt_pool.json").exists())
didx = {d: i for i, d in enumerate(days)}


def load(day):
    return json.loads((ROOT / day / "zt_pool.json").read_text(encoding="utf-8"))


def dump_stock(code, buy):
    i = didx[buy]
    window = days[i - 3 : i + 1]
    print("=" * 80)
    print(f"CODE {code} buy={buy}  window={window}")
    for d in window:
        data = load(d)
        hit = next((s for s in data["stocks"] if str(s["code"]).zfill(6) == code), None)
        print(f"\n--- {d}  全场涨停{data.get('count')} H={data.get('max_board')} ---")
        if hit:
            print(
                f"  SELF {hit.get('name')} boards={hit.get('boards')} "
                f"theme={hit.get('theme')} turnover={hit.get('turnover_rate')}"
            )
            print(f"  tags={hit.get('theme_tags_text')}")
        else:
            print("  SELF 不在涨停池")

        # theme frequency that day
        themes = {}
        for s in data["stocks"]:
            t = s.get("theme") or "?"
            themes[t] = themes.get(t, 0) + 1
        top = sorted(themes.items(), key=lambda x: -x[1])[:12]
        print("  theme top:", ", ".join(f"{k}:{v}" for k, v in top))


cases = [
    ("600881", "2024-09-26"),
    ("002730", "2024-12-25"),
    ("603928", "2025-01-22"),
]
for code, buy in cases:
    dump_stock(code, buy)
