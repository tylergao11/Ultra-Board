# -*- coding: utf-8 -*-
import io, sys, json
from pathlib import Path

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8")
raw = Path(r"D:\Ultra-Board\data\kaipanla\raw")
print(f"{'日期':<12}{'ZT':>5}{'SJZT':>6}{'STZT':>5}{'梯队':>6}{'vsSJZT':>8}{'vsZT':>6}")
for d in sorted(raw.iterdir()):
    zf, lad = d / "HisZhangFuDetail.json", d / "ladder.json"
    if not (d / "_DONE").exists() or not lad.exists():
        continue
    info = json.loads(zf.read_text(encoding="utf-8")).get("info") or {}
    zt = int(info.get("ZT") or 0)
    sj = int(info.get("SJZT") or 0)
    st = int(info.get("STZT") or 0)
    L = json.loads(lad.read_text(encoding="utf-8")).get("ladder") or {}
    n = sum(len(v) for v in L.values())
    print(f"{d.name:<12}{zt:>5}{sj:>6}{st:>5}{n:>6}{sj-n:>8}{zt-n:>6}")

# akshare 对照一天
print("\n### akshare 涨停池对照 2025-11-05 ###")
try:
    import akshare as ak
    df = ak.stock_zt_pool_em(date="20251105")
    print(f"akshare rows={len(df)}")
    print("连板分布:\n", df["连板数"].value_counts().sort_index(ascending=False).to_string())
    # 与 ladder 代码对比
    L = json.loads((raw / "2025-11-05" / "ladder.json").read_text(encoding="utf-8")).get("ladder") or {}
    kpl = {r[0] for rows in L.values() for r in rows if isinstance(r, list)}
    ak_codes = set(df["代码"].astype(str))
    print(f"kpl={len(kpl)} ak={len(ak_codes)} 交集={len(kpl&ak_codes)} 仅ak={len(ak_codes-kpl)} 仅kpl={len(kpl-ak_codes)}")
    only_ak = df[df["代码"].astype(str).isin(ak_codes - kpl)][["代码", "名称", "连板数", "所属行业"]].head(20)
    print("仅 akshare 有（开盘啦 ladder 没有）:")
    print(only_ak.to_string(index=False))
except Exception as e:
    print("FAIL", type(e).__name__, e)
