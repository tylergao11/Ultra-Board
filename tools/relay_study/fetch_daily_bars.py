# -*- coding: utf-8 -*-
"""Bounded daily-bar fetch for the lianban candidate universe.

Uses the same Tonghuashun stock-line endpoint already called by
ultraboard.ths.limit_pool (trade-day verification). Does NOT touch
ultraboard/ or data contracts. Bars land under
tools/relay_study/out/daily_bars/{code}.json.

One last3600 request per code. Resume-safe. Stop on repeated failures.
"""
from __future__ import annotations

import csv
import json
import random
import re
import sys
import time
from pathlib import Path

import requests

STUDY = Path(__file__).resolve().parent
OUT = STUDY / "out"
BAR_DIR = OUT / "daily_bars"
CAND = OUT / "candidates.csv"
KEEP_START = "2025-09-01"
KEEP_END = "2026-08-20"
ENDPOINT = "https://d.10jqka.com.cn/v6/line/hs_{code}/01/last3600.js"
MIN_GAP = 0.7
MAX_GAP = 1.3
STOP_AFTER = 6


def _session() -> requests.Session:
    s = requests.Session()
    s.trust_env = False
    s.proxies = {"http": "", "https": ""}
    s.headers.update({
        "User-Agent": (
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
            "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36"
        ),
        "Accept": "text/plain,*/*",
    })
    return s


def parse_body(text: str, label: str) -> dict:
    text = text.strip()
    left = text.find("(")
    right = text.rfind(")")
    if left < 0 or right <= left:
        raise RuntimeError("not jsonp: " + label)
    body = json.loads(text[left + 1:right])
    if not isinstance(body, dict):
        raise RuntimeError("not object: " + label)
    return body


def parse_bars(body: dict, label: str) -> dict:
    raw = body.get("data")
    if raw in (None, ""):
        return {}
    if not isinstance(raw, str):
        raise RuntimeError("data not str: " + label)
    out = {}
    for rec in raw.split(";"):
        if not rec.strip():
            continue
        parts = rec.split(",")
        if len(parts) < 7:
            raise RuntimeError("short bar: " + label)
        compact = parts[0]
        if not re.fullmatch(r"\d{8}", compact):
            raise RuntimeError("bad date: " + label + " " + compact)
        day = compact[:4] + "-" + compact[4:6] + "-" + compact[6:]
        if day < KEEP_START or day > KEEP_END:
            continue
        if any(parts[i] in ("", None) for i in range(1, 5)):
            continue
        out[day] = {
            "o": float(parts[1]),
            "h": float(parts[2]),
            "l": float(parts[3]),
            "c": float(parts[4]),
            "v": float(parts[5]) if parts[5] not in ("",) else None,
            "amt": float(parts[6]) if parts[6] not in ("",) else None,
        }
    return out


def candidate_codes():
    with CAND.open(encoding="utf-8-sig", newline="") as f:
        rows = list(csv.DictReader(f))
    return sorted({r["code"].strip() for r in rows if r.get("code")})


def main() -> int:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    BAR_DIR.mkdir(parents=True, exist_ok=True)
    codes = candidate_codes()
    sess = _session()
    done = 0
    skipped = 0
    failed = []
    consec = 0
    t0 = time.time()
    for i, code in enumerate(codes, 1):
        dest = BAR_DIR / (code + ".json")
        if dest.exists() and dest.stat().st_size > 20:
            skipped += 1
            done += 1
            continue
        time.sleep(random.uniform(MIN_GAP, MAX_GAP))
        url = ENDPOINT.format(code=code)
        try:
            r = sess.get(
                url,
                headers={"Referer": "https://stockpage.10jqka.com.cn/" + code + "/"},
                timeout=20,
            )
            r.raise_for_status()
            body = parse_body(r.text, code)
            bars = parse_bars(body, code)
            if not bars:
                raise RuntimeError("empty bars in window")
            payload = {
                "code": code,
                "name": body.get("name"),
                "source": "ths_v6_line_last3600",
                "n_bars": len(bars),
                "bars": bars,
            }
            dest.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
            consec = 0
            done += 1
            if i % 25 == 0 or i == len(codes):
                msg = "[%d/%d] ok=%d skip=%d fail=%d last=%s bars=%d elapsed=%.0fs" % (
                    i, len(codes), done, skipped, len(failed), code, len(bars), time.time() - t0
                )
                print(msg, flush=True)
        except Exception as exc:
            consec += 1
            failed.append("%s: %s: %s" % (code, type(exc).__name__, exc))
            print("FAIL %s: %s" % (code, exc), flush=True)
            if consec >= STOP_AFTER:
                print("STOP after %d consecutive failures" % STOP_AFTER, flush=True)
                break
    (OUT / "daily_bars_fetch_log.json").write_text(
        json.dumps(
            {
                "universe": len(codes),
                "done": done,
                "skipped_existing": skipped,
                "failed": failed,
                "elapsed_s": round(time.time() - t0, 1),
            },
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )
    print("done=%d/%d failed=%d" % (done, len(codes), len(failed)), flush=True)
    return 1 if failed and consec >= STOP_AFTER else 0


if __name__ == "__main__":
    raise SystemExit(main())
