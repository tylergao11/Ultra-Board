# -*- coding: utf-8 -*-
"""查 2025-10-09 多出来的 2 只是什么"""
import io, json, sys
from pathlib import Path

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8")
ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from ultraboard.kaipanla.client import KaipanlaClient, ok

DAY = "2025-10-09"
dd = ROOT / "data" / "kaipanla" / "raw" / DAY
pool = json.loads((dd / "zt_pool.json").read_text(encoding="utf-8"))
sec = json.loads((dd / "sector_ladder.json").read_text(encoding="utf-8"))
sent = json.loads((dd / "sentiment.json").read_text(encoding="utf-8"))

print("sentiment keys in info:", list((sent.get("info") or {}).keys()))
info = sent["info"]
for k in ("ZT", "SJZT", "STZT", "DT", "SJDT", "STDT"):
    print(f"  {k}={info.get(k)}")

print(f"\npool count={pool['count']} sjzt={pool['sjzt']}")
print(f"board_counts={pool['board_counts']}")
print(f"fanbao_count={pool['fanbao_count']}")

# 板块梯队里的正常票 + 反包
tier_codes = set()
fanbao_codes = set()
for s in sec["sectors"]:
    for t, stocks in s.get("tiers", {}).items():
        for x in stocks:
            tier_codes.add(x["code"])
    for x in s.get("fanbao", []):
        fanbao_codes.add(x["code"])

pool_codes = {s["code"] for s in pool["stocks"]}
print(f"\nsector 正常梯队票={len(tier_codes)} 反包={len(fanbao_codes)}")
print(f"在 pool 不在 sector 梯队+反包: {sorted(pool_codes - tier_codes - fanbao_codes)}")
print(f"在 sector 不在 pool: {sorted((tier_codes | fanbao_codes) - pool_codes)}")

# 对照 akshare
print("\n=== akshare 对照 ===")
try:
    import akshare as ak
    df = ak.stock_zt_pool_em(date="20251009")
    print(f"akshare 涨停池={len(df)}")
    ak_codes = set(df["代码"].astype(str))
    only_pool = pool_codes - ak_codes
    only_ak = ak_codes - pool_codes
    print(f"仅开盘啦: {len(only_pool)} {sorted(only_pool)}")
    print(f"仅 akshare: {len(only_ak)} {sorted(list(only_ak))[:20]}")
    if only_pool:
        print("\n仅开盘啦明细:")
        for s in pool["stocks"]:
            if s["code"] in only_pool:
                print(f"  {s['boards']}板 {s['code']} {s['name']} "
                      f"题材={s['theme']} 描述={s['boards_desc']!r} 反包={s['is_fanbao']}")
    # ST in akshare
    st = df[df["名称"].str.contains("ST", case=False, na=False)]
    print(f"\nakshare 含ST: {len(st)}")
    print(st[["代码", "名称", "连板数"]].head(15).to_string(index=False))
except Exception as e:
    print("akshare FAIL", type(e).__name__, e)

# 再看 expression 一板二板数字
expr = json.loads((dd / "expression.json").read_text(encoding="utf-8"))
print(f"\nexpression.info = {expr.get('info')}")
