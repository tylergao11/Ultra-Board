import json
from pathlib import Path

ROOT = Path("data/kaipanla/raw")
days = sorted(
    p.name
    for p in ROOT.iterdir()
    if p.is_dir() and (p / "zt_pool.json").exists()
)
didx = {d: i for i, d in enumerate(days)}

bought = {
    "001379",
    "600326",
    "000062",
    "002302",
    "603626",
    "000566",
    "002583",
    "600881",
    "002628",
    "002542",
    "000833",
    "002348",
    "002730",
    "000533",
    "002917",
    "603928",
    "605398",
    "601177",
    "002522",
    "002910",
    "603700",
    "000665",
    "603677",
    "002278",
    "002767",
    "002549",
}


def load(day):
    p = ROOT / day / "zt_pool.json"
    if not p.exists():
        return None
    return json.loads(p.read_text(encoding="utf-8"))


def stocks(day, min_boards=2):
    data = load(day)
    if not data:
        return []
    rows = []
    for s in data.get("stocks") or []:
        b = s.get("boards") or 0
        if b < min_boards:
            continue
        rows.append(s)
    rows.sort(key=lambda x: (-(x.get("boards") or 0), x.get("code")))
    return rows


def future_last(code, start, horizon=15):
    if start not in didx:
        return None, None
    last_d, last_b = None, None
    end = min(len(days), didx[start] + horizon + 1)
    for d in days[didx[start] : end]:
        data = load(d)
        if not data:
            continue
        hit = next(
            (s for s in data.get("stocks") or [] if str(s.get("code")).zfill(6) == code),
            None,
        )
        if hit:
            last_d, last_b = d, hit.get("boards")
        elif last_d:
            break
    return last_d, last_b


def dump(title, day, min_boards=3):
    data = load(day)
    if not data:
        print(f"\n### {title} {day} 无文件")
        return
    print(
        f"\n### {title} {day}  涨停{data.get('count')} H={data.get('max_board')}"
    )
    for s in stocks(day, min_boards):
        code = str(s.get("code")).zfill(6)
        last_d, last_b = future_last(code, day, 20)
        extra = (last_b - (s.get("boards") or 0)) if last_b is not None else None
        mark = "已买" if code in bought else ""
        print(
            f"  {code} {s.get('name')} {s.get('boards')}板 {s.get('theme')} "
            f"换手{s.get('turnover_rate')} 此后->{last_b}板/{last_d} extra={extra} {mark}"
        )


# 断板日 / 空窗关键日
windows = [
    ("腾达断板，空窗开始", "2024-08-06", 3),
    ("腾达空窗中", "2024-08-08", 3),
    ("腾达空窗中", "2024-08-09", 3),
    ("腾达空窗中", "2024-08-12", 3),
    ("腾达空窗中/天路出生", "2024-08-13", 3),
    ("天路买日", "2024-08-15", 3),
    ("天路断", "2024-08-16", 3),
    ("华强买日前", "2024-08-19", 3),
    ("华强9板切西部", "2024-08-27", 3),
    ("西部断", "2024-08-30", 3),
    ("科森断", "2024-09-09", 3),
    ("海药断，冰点", "2024-09-18", 3),
    ("海能达出生", "2024-09-19", 3),
    ("海能达买日前", "2024-09-24", 3),
    ("亚泰切日", "2024-09-26", 3),
    ("亚泰断，地产清空", "2024-10-09", 3),
    ("亚泰空窗", "2024-10-10", 3),
    ("亚泰空窗", "2024-10-11", 3),
    ("亚泰空窗", "2024-10-14", 3),
    ("亚泰空窗", "2024-10-15", 3),
    ("亚泰空窗", "2024-10-16", 3),
    ("路桥断/中化出生", "2024-10-24", 3),
    ("中化买日前", "2024-10-28", 3),
    ("中化断", "2024-11-08", 3),
    ("中化空窗", "2024-11-11", 3),
    ("中化空窗", "2024-11-12", 3),
    ("中化空窗", "2024-11-13", 3),
    ("中化空窗", "2024-11-14", 3),
    ("粤桂断/高乐", "2024-11-26", 3),
    ("高乐跑路日", "2024-11-27", 3),
    ("失败后空窗", "2024-11-28", 3),
    ("失败后空窗", "2024-11-29", 3),
    ("失败后空窗", "2024-12-02", 3),
    ("失败后空窗", "2024-12-03", 3),
    ("失败后空窗", "2024-12-04", 3),
    ("失败后空窗", "2024-12-05", 3),
    ("失败后空窗", "2024-12-06", 3),
    ("失败后空窗", "2024-12-09", 3),
    ("失败后空窗", "2024-12-10", 3),
    ("失败后空窗", "2024-12-11", 3),
    ("失败后空窗", "2024-12-12", 3),
    ("失败后空窗", "2024-12-13", 3),
    ("失败后空窗", "2024-12-16", 3),
    ("失败后空窗", "2024-12-17", 3),
    ("失败后空窗", "2024-12-18", 3),
    ("失败后空窗", "2024-12-19", 3),
    ("失败后空窗", "2024-12-20", 3),
    ("顺钠断", "2025-01-06", 3),
    ("顺钠空窗", "2025-01-07", 3),
    ("顺钠空窗", "2025-01-08", 3),
    ("顺钠空窗", "2025-01-09", 3),
    ("顺钠空窗", "2025-01-10", 3),
    ("杭齿断/众成", "2025-02-24", 3),
    ("众成断", "2025-02-25", 3),
    ("广电断/奇精", "2025-03-13", 3),
    ("神开切日", "2025-03-20", 3),
    ("神开断/先锋", "2025-03-24", 3),
    ("先锋断", "2025-03-26", 3),
    ("先锋空窗", "2025-03-27", 3),
    ("先锋空窗", "2025-03-28", 3),
    ("先锋空窗", "2025-03-31", 3),
]

for title, day, mb in windows:
    dump(title, day, mb)
