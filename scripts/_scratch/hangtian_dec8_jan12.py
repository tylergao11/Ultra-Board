# -*- coding: utf-8 -*-
import json
import sys
from datetime import datetime, timezone, timedelta
from pathlib import Path

sys.stdout.reconfigure(encoding="utf-8")
CN = timezone(timedelta(hours=8))
ROOT = Path(r"C:\Ai\Ultra-Board\data\kaipanla\raw")
THS = Path(r"C:\Ai\Ultra-Board\data\ths\open_limit_pool")


def days_between():
    out = []
    for p in sorted(ROOT.iterdir()):
        if (
            p.is_dir()
            and "2025-12-08" <= p.name <= "2026-01-12"
            and (p / "zt_pool.json").exists()
        ):
            out.append(p.name)
    return out


def ts(v):
    if not v:
        return ""
    return datetime.fromtimestamp(int(v), CN).strftime("%H:%M")


def load(day):
    return json.loads((ROOT / day / "zt_pool.json").read_text(encoding="utf-8"))


def is_hangtian(s):
    theme = str(s.get("theme") or "")
    raw = s.get("raw") or []
    tags = str(s.get("theme_tags_text") or (raw[12] if len(raw) > 12 else "") or "")
    main = "航天" in theme
    attr = "航天" in tags or "航天" in theme
    return main, attr, theme, tags


days = days_between()
print("days", len(days), days[0], days[-1])
print()
print("==== 000547 航天发展 ====")
for d in days:
    data = load(d)
    hit = next(
        (
            s
            for s in data.get("stocks") or []
            if str(s.get("code")).zfill(6) == "000547"
        ),
        None,
    )
    if hit:
        _main, _attr, theme, _tags = is_hangtian(hit)
        oc = hit.get("open_count")
        raw = hit.get("raw") or []
        if oc is None and len(raw) > 16:
            oc = raw[16]
        print(
            f"{d} 在池 {hit.get('boards')} {hit.get('boards_desc')} "
            f"主题={theme} 换手={hit.get('turnover_rate')} "
            f"首封={ts(hit.get('first_limit_ts'))} 开板={oc}"
        )
        continue
    exploded = None
    op = THS / f"{d}.json"
    if op.exists():
        od = json.loads(op.read_text(encoding="utf-8-sig"))
        rows = od if isinstance(od, list) else od.get("stocks") or od.get("pool") or []
        exploded = next(
            (s for s in rows if str(s.get("code") or "").zfill(6) == "000547"),
            None,
        )
    if exploded:
        print(
            f"{d} 炸板 换手={exploded.get('turnover_rate')} "
            f"涨跌={exploded.get('change_rate')} "
            f"开板={exploded.get('open_count')} "
            f"首封={exploded.get('first_limit_time')}"
        )
    else:
        print(f"{d} 不在涨停/炸板池")

print()
print("==== 航天主标签 / 属性含航天 ====")
prev_main_h = prev_attr_h = None
for d in days:
    data = load(d)
    stocks = data.get("stocks") or []
    main_s = []
    attr_s = []
    for s in stocks:
        main, attr, _theme, _tags = is_hangtian(s)
        if main:
            main_s.append(s)
        if attr:
            attr_s.append(s)

    def top(xs):
        if not xs:
            return 0, 0, "-"
        xs = sorted(xs, key=lambda s: (-int(s.get("boards") or 0), str(s.get("name"))))
        h = int(xs[0].get("boards") or 0)
        names = ",".join(f"{x.get('name')}{x.get('boards')}" for x in xs[:6])
        return h, len(xs), names

    mh, mn, mnames = top(main_s)
    ah, an, anames = top(attr_s)
    if prev_main_h is None:
        mfb = ""
    elif mh < prev_main_h:
        mfb = "高度掉"
    elif mh == prev_main_h:
        mfb = "平"
    else:
        mfb = "高度升"
    if prev_attr_h is None:
        afb = ""
    elif ah < prev_attr_h:
        afb = "高度掉"
    elif ah == prev_attr_h:
        afb = "平"
    else:
        afb = "高度升"
    print(
        f"{d} 全场最高{data.get('max_board')} "
        f"主{mn}家高{mh}{mfb} [{mnames}] | "
        f"属{an}家高{ah}{afb} [{anames}]"
    )
    prev_main_h, prev_attr_h = mh, ah
