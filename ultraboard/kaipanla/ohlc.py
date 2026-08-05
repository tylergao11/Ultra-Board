# -*- coding: utf-8 -*-
"""用日 K 补开盘价 / 开盘涨幅，挂到主源日目录。

规则：
  - **仅 ≥2 板**需要开盘价；首板不拉、不写 open/open_pct
  - 腾讯日 K 优先，失败走新浪

产物（每个交易日）：
  data/kaipanla/raw/YYYY-MM-DD/ohlc.json
    仅含当日 ≥2 板代码 → { open, high, low, close, prev_close, volume, open_pct }

并写回同日 zt_pool.json 的 ≥2 板票：
  open, high, low, prev_close, open_pct
  （首板票若曾被误写，会清掉这些字段）

缓存：data/kaipanla/ohlc_cache/{code}.json

用法：
  python -m ultraboard.kaipanla.ohlc
  python -m ultraboard.kaipanla.ohlc --day 2026-08-03
"""
from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path
from typing import Any

import requests
import urllib3

urllib3.disable_warnings()

ROOT = Path(__file__).resolve().parents[2]
DATA_DIR = ROOT / "data" / "kaipanla"
RAW_DIR = DATA_DIR / "raw"
CACHE_DIR = DATA_DIR / "ohlc_cache"
CACHE_PRICE_MODE = "unadjusted"

# 腾讯日 K 为主（东财当前环境连不上）；新浪作兜底
TENCENT_KLINE = "https://web.ifzq.gtimg.cn/appstock/app/fqkline/get"
SINA_KLINE = (
    "https://money.finance.sina.com.cn/quotes_service/api/json_v2.php/"
    "CN_MarketData.getKLineData"
)
_SESSION = requests.Session()
_SESSION.trust_env = False  # 避开坏掉的系统代理
_SESSION.proxies = {"http": "", "https": ""}
_SESSION.headers.update({
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36"
    ),
    "Accept": "*/*",
})


def _read_json(path: Path, default=None):
    if not path.exists():
        return default
    return json.loads(path.read_text(encoding="utf-8-sig"))


def _write_json(path: Path, obj: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(obj, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )


def to_symbol(code: str) -> str | None:
    """腾讯/新浪代码：sh600000 / sz000001。北交所跳过。"""
    c = str(code).strip().zfill(6)
    if c.startswith(("4", "8", "92")):
        return None
    if c.startswith(("5", "6", "9")):
        return f"sh{c}"
    if c.startswith(("0", "3")):
        return f"sz{c}"
    return None


def to_secid(code: str) -> str | None:
    """兼容旧名。"""
    return to_symbol(code)


def list_raw_days() -> list[str]:
    if not RAW_DIR.is_dir():
        return []
    days = []
    for p in RAW_DIR.iterdir():
        if p.is_dir() and (p / "zt_pool.json").exists():
            days.append(p.name)
    return sorted(days)


def codes_needed(
    days: list[str] | None = None,
) -> tuple[dict[str, set[str]], str, str]:
    """code -> dates（仅 boards≥2 的日）；首板不参与。"""
    days = days or list_raw_days()
    by_code: dict[str, set[str]] = {}
    for d in days:
        zt = _read_json(RAW_DIR / d / "zt_pool.json", {})
        for s in zt.get("stocks") or []:
            try:
                if int(s.get("boards") or 0) < 2:
                    continue
            except (TypeError, ValueError):
                continue
            code = str(s.get("code") or "").zfill(6)
            if not code or to_symbol(code) is None:
                continue
            by_code.setdefault(code, set()).add(d)
    if not by_code:
        return {}, "", ""
    all_days = sorted({d for ds in by_code.values() for d in ds})
    return by_code, all_days[0], all_days[-1]


def _bars_from_rows(
    rows: list[tuple[str, float, float, float, float, float]],
) -> dict[str, dict[str, Any]]:
    """rows: (day, open, close, high, low, volume) 按日期升序。"""
    out: dict[str, dict[str, Any]] = {}
    prev_close: float | None = None
    for day, o, c, h, low, vol in rows:
        if prev_close and prev_close > 0:
            open_pct = round((o / prev_close - 1.0) * 100.0, 2)
            bar_prev = prev_close
        else:
            open_pct = None
            bar_prev = None
        out[day] = {
            "open": o,
            "close": c,
            "high": h,
            "low": low,
            "prev_close": bar_prev,
            "volume": vol,
            "amount": None,
            "open_pct": open_pct,
        }
        prev_close = c
    return out


def _fetch_tencent(code: str, beg: str, end: str) -> dict[str, dict[str, Any]]:
    sym = to_symbol(code)
    if not sym:
        return {}
    # 涨停池保存真实成交价，补K线必须同样使用不复权价格；前复权会在除权后
    # 追溯改写历史价格，造成跨日收益出现物理上不可能的跳变。
    param = f"{sym},day,{beg},{end},1000,none"
    r = _SESSION.get(TENCENT_KLINE, params={"param": param}, timeout=15)
    r.raise_for_status()
    body = r.json()
    data = (body.get("data") or {}).get(sym) or {}
    series = data.get("day") or []
    rows: list[tuple[str, float, float, float, float, float]] = []
    for item in series:
        # [date, open, close, high, low, volume]
        if not item or len(item) < 6:
            continue
        day = str(item[0])[:10]
        if day < beg or day > end:
            continue
        rows.append((
            day,
            float(item[1]),
            float(item[2]),
            float(item[3]),
            float(item[4]),
            float(item[5]),
        ))
    rows.sort(key=lambda x: x[0])
    # 为算首日 open_pct，多取一根前收：若被 beg 截断，再拉稍长区间
    if rows and rows[0][0] == beg:
        # 试着向前多取几天补 prev_close
        param2 = f"{sym},day,,{beg},5,none"
        r2 = _SESSION.get(TENCENT_KLINE, params={"param": param2}, timeout=15)
        if r2.ok:
            data2 = (r2.json().get("data") or {}).get(sym) or {}
            series2 = data2.get("day") or []
            pre_rows = []
            for item in series2:
                if not item or len(item) < 6:
                    continue
                day = str(item[0])[:10]
                if day < beg:
                    pre_rows.append((
                        day,
                        float(item[1]),
                        float(item[2]),
                        float(item[3]),
                        float(item[4]),
                        float(item[5]),
                    ))
            if pre_rows:
                pre_rows.sort(key=lambda x: x[0])
                rows = pre_rows[-1:] + rows
    bars = _bars_from_rows(rows)
    # 丢掉仅为 prev 的前导日（若 < beg）
    return {d: b for d, b in bars.items() if beg <= d <= end}


def _fetch_sina(code: str, beg: str, end: str) -> dict[str, dict[str, Any]]:
    sym = to_symbol(code)
    if not sym:
        return {}
    r = _SESSION.get(
        SINA_KLINE,
        params={"symbol": sym, "scale": "240", "ma": "no", "datalen": "1023"},
        timeout=15,
    )
    r.raise_for_status()
    arr = r.json()
    if not isinstance(arr, list):
        return {}
    rows: list[tuple[str, float, float, float, float, float]] = []
    for item in arr:
        day = str(item.get("day") or "")[:10]
        if not day or day < beg or day > end:
            # 仍收集 beg 前一天供 prev
            if day and day < beg:
                rows.append((
                    day,
                    float(item["open"]),
                    float(item["close"]),
                    float(item["high"]),
                    float(item["low"]),
                    float(item.get("volume") or 0),
                ))
            continue
        rows.append((
            day,
            float(item["open"]),
            float(item["close"]),
            float(item["high"]),
            float(item["low"]),
            float(item.get("volume") or 0),
        ))
    # 含 beg 前的最后一根
    rows.sort(key=lambda x: x[0])
    # 保留 beg 前最多 1 根
    pre = [x for x in rows if x[0] < beg]
    mid = [x for x in rows if beg <= x[0] <= end]
    use = (pre[-1:] if pre else []) + mid
    bars = _bars_from_rows(use)
    return {d: b for d, b in bars.items() if beg <= d <= end}


def fetch_kline_range(
    code: str,
    beg: str,
    end: str,
    *,
    retries: int = 3,
) -> dict[str, dict[str, Any]]:
    """拉 [beg, end] 日 K，返回 date -> bar。腾讯优先，失败/空则新浪。"""
    if not to_symbol(code):
        return {}
    last_err: Exception | None = None
    for attempt in range(retries):
        # 腾讯
        try:
            bars = _fetch_tencent(code, beg, end)
            if bars:
                return bars
        except Exception as e:
            last_err = e
        # 新浪兜底
        try:
            bars = _fetch_sina(code, beg, end)
            if bars:
                return bars
        except Exception as e:
            last_err = e
        time.sleep(0.25 * (attempt + 1))
    raise RuntimeError(f"{code} kline failed: {last_err}")


def load_or_fetch_code(
    code: str,
    beg: str,
    end: str,
    *,
    force: bool = False,
    sleep_s: float = 0.15,
) -> dict[str, dict[str, Any]]:
    cache_path = CACHE_DIR / f"{code}.json"
    cached = {} if force else (_read_json(cache_path, {}) or {})
    if cached.get("price_mode") != CACHE_PRICE_MODE:
        cached = {}
    bars: dict[str, dict] = dict(cached.get("bars") or {})

    need_refresh = force or not bars
    if not need_refresh:
        # 缓存须覆盖该票用到的起止日（至少含 beg/end 两端）
        if beg not in bars or end not in bars:
            need_refresh = True

    if need_refresh:
        time.sleep(sleep_s)
        try:
            fetched = fetch_kline_range(code, beg, end)
        except Exception as e:
            print(f"  FAIL {code}: {e}", flush=True)
            return bars
        if fetched:
            # 窄区间补数只能增量覆盖同日期，不能抹掉缓存中其他历史日期。
            # force=True 时 bars 本来就是空字典，仍保持完整重拉语义。
            bars = {**bars, **fetched}
            _write_json(cache_path, {
                "code": code,
                "symbol": to_symbol(code),
                "price_mode": CACHE_PRICE_MODE,
                "beg": min(bars),
                "end": max(bars),
                "bars": bars,
            })
    return bars


def project_day_ohlc(
    day: str,
    code_bars: dict[str, dict[str, dict[str, Any]]],
) -> dict[str, dict[str, Any]]:
    """某日 code -> ohlc 子集。"""
    out = {}
    for code, bars in code_bars.items():
        if day in bars:
            out[code] = bars[day]
    return out


_OHLC_KEYS = ("open", "high", "low", "prev_close", "open_pct", "amount_em")


def merge_into_zt_pool(day: str, ohlc_map: dict[str, dict[str, Any]]) -> int:
    """把 open/open_pct 写进 zt_pool 的 ≥2 板票；首板清掉开盘字段。"""
    path = RAW_DIR / day / "zt_pool.json"
    zt = _read_json(path)
    if not zt:
        return 0
    n = 0
    for s in zt.get("stocks") or []:
        code = str(s.get("code") or "").zfill(6)
        try:
            boards = int(s.get("boards") or 0)
        except (TypeError, ValueError):
            boards = 0
        if boards < 2:
            # 首板不需要开盘价
            for k in _OHLC_KEYS:
                s.pop(k, None)
            continue
        bar = ohlc_map.get(code)
        if not bar:
            continue
        s["open"] = bar.get("open")
        s["high"] = bar.get("high")
        s["low"] = bar.get("low")
        s["prev_close"] = bar.get("prev_close")
        s["open_pct"] = bar.get("open_pct")
        if bar.get("amount") is not None:
            s["amount_em"] = bar.get("amount")
        n += 1
    _write_json(path, zt)
    return n


def enrich(
    days: list[str] | None = None,
    *,
    force: bool = False,
    sleep_s: float = 0.12,
    patch_zt_pool: bool = True,
) -> dict[str, Any]:
    raw_days = days or list_raw_days()
    by_code, beg, end = codes_needed(raw_days)
    if not by_code:
        return {"days": 0, "codes": 0, "msg": "no codes"}

    print(
        f"OHLC enrich: days={len(raw_days)} codes={len(by_code)} "
        f"range={beg}→{end} force={force}",
        flush=True,
    )

    code_bars: dict[str, dict[str, dict[str, Any]]] = {}
    for i, code in enumerate(sorted(by_code.keys()), 1):
        # 该票实际需要的日期范围可收窄
        ds = sorted(by_code[code])
        c_beg, c_end = ds[0], ds[-1]
        bars = load_or_fetch_code(
            code, c_beg, c_end, force=force, sleep_s=sleep_s
        )
        code_bars[code] = bars
        if i % 50 == 0 or i == len(by_code):
            print(f"  fetch {i}/{len(by_code)}", flush=True)

    patched = 0
    for day in raw_days:
        ohlc_map = project_day_ohlc(day, code_bars)
        # 只保留当日 ≥2 板
        zt = _read_json(RAW_DIR / day / "zt_pool.json", {})
        ge2_codes = set()
        for s in zt.get("stocks") or []:
            try:
                if int(s.get("boards") or 0) < 2:
                    continue
            except (TypeError, ValueError):
                continue
            ge2_codes.add(str(s.get("code") or "").zfill(6))
        day_map = {c: ohlc_map[c] for c in ge2_codes if c in ohlc_map}
        _write_json(RAW_DIR / day / "ohlc.json", {
            "date": day,
            "source": "tencent_kline/sina_fallback",
            "count": len(day_map),
            "stocks": day_map,
        })
        if patch_zt_pool:
            patched += merge_into_zt_pool(day, day_map)
        hit = len(day_map)
        total = len(ge2_codes)
        print(f"  {day} ohlc ≥2 {hit}/{total}", flush=True)

    return {
        "days": len(raw_days),
        "codes": len(by_code),
        "patched_stock_rows": patched,
        "beg": beg,
        "end": end,
    }


def load_day_ohlc(day: str) -> dict[str, dict[str, Any]]:
    """供主源读取：优先 ohlc.json。"""
    doc = _read_json(RAW_DIR / day / "ohlc.json", {}) or {}
    return dict(doc.get("stocks") or {})


def attach_ohlc_to_stocks(day: str, stocks: list[dict]) -> list[dict]:
    """给 ≥2 板挂 open/open_pct（不写盘）；首板不挂。"""
    m = load_day_ohlc(day)
    if not m:
        return stocks
    out = []
    for s in stocks:
        item = dict(s)
        try:
            boards = int(item.get("boards") or 0)
        except (TypeError, ValueError):
            boards = 0
        if boards < 2:
            for k in _OHLC_KEYS:
                item.pop(k, None)
            out.append(item)
            continue
        code = str(item.get("code") or "").zfill(6)
        bar = m.get(code)
        if not bar:
            out.append(item)
            continue
        item.setdefault("open", bar.get("open"))
        item.setdefault("high", bar.get("high"))
        item.setdefault("low", bar.get("low"))
        item.setdefault("prev_close", bar.get("prev_close"))
        item.setdefault("open_pct", bar.get("open_pct"))
        out.append(item)
    return out


def main(argv: list[str] | None = None) -> int:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    ap = argparse.ArgumentParser(description="东财日K补开盘价到 raw 日目录")
    ap.add_argument("--day", action="append", help="指定日期 YYYY-MM-DD，可多次")
    ap.add_argument("--force", action="store_true", help="忽略缓存重拉")
    ap.add_argument(
        "--no-patch-zt",
        action="store_true",
        help="只写 ohlc.json，不改 zt_pool.json",
    )
    ap.add_argument("--sleep", type=float, default=0.12, help="每票间隔秒")
    args = ap.parse_args(argv)

    days = args.day
    if days:
        for d in days:
            if not (RAW_DIR / d / "zt_pool.json").exists():
                print(f"missing zt_pool: {d}", file=sys.stderr)
                return 2

    summary = enrich(
        days=days,
        force=args.force,
        sleep_s=args.sleep,
        patch_zt_pool=not args.no_patch_zt,
    )
    print("ok", summary, flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
