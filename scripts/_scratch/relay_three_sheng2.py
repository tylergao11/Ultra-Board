import json
from pathlib import Path

ROOT = Path("data/kaipanla/raw")


def load(day):
    return json.loads((ROOT / day / "zt_pool.json").read_text(encoding="utf-8"))


def names_by_theme(day, keys):
    rows = []
    for s in load(day)["stocks"]:
        blob = (s.get("theme") or "") + "|" + (s.get("theme_tags_text") or "")
        if any(k in blob for k in keys):
            rows.append((s["name"], s.get("theme"), s.get("theme_tags_text"), s.get("boards")))
    return rows


def names_exact(day, keys):
    return [
        (s["name"], s.get("theme"), s.get("boards"))
        for s in load(day)["stocks"]
        if (s.get("theme") or "") in keys
    ]


print("=== 亚泰 地产 ===")
for d in ["2024-09-23", "2024-09-24", "2024-09-25", "2024-09-26"]:
    exact = names_exact(d, {"房地产", "地产链"})
    fuzzy = names_by_theme(d, ["房地产"])
    print(f"{d} exact地产/地产链={len(exact)} {[x[0]+'/'+x[1] for x in exact]}")
    print(f"       子串'房地产'={len(fuzzy)} {[x[0]+'/'+x[1] for x in fuzzy]}")

print("\n=== 电光 算力 exact vs 子串 ===")
for d in ["2024-12-20", "2024-12-23", "2024-12-24", "2024-12-25"]:
    exact = names_exact(d, {"算力"})
    fuzzy = names_by_theme(d, ["算力"])
    print(f"{d} exact算力={len(exact)} {[x[0] for x in exact]}  子串={len(fuzzy)} {[x[0]+'/'+x[1] for x in fuzzy]}")

print("\n=== 兴业 芯片 exact vs 子串 ===")
for d in ["2025-01-17", "2025-01-20", "2025-01-21", "2025-01-22"]:
    exact = names_exact(d, {"芯片"})
    fuzzy = names_by_theme(d, ["芯片"])
    photo = names_exact(d, {"光刻胶"})
    print(f"{d} exact芯片={len(exact)} {[x[0] for x in exact]}  子串芯片={len(fuzzy)} {[x[0]+'/'+x[1] for x in fuzzy]}  exact光刻胶={len(photo)} {[x[0] for x in photo]}")
