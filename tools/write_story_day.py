# -*- coding: utf-8 -*-
"""将人工核对后的单日故事写入契约路径（不读 OCR、不造题材）。

用法（由录入流程调用，输入已是结构化标题/个股行）：

  python tools/write_story_day.py 2025-11-12 --payload path/to/payload.json

payload.json:
{
  "stories": [
    {
      "context": "大消费",
      "story": "10月份CPI同比涨幅转正",
      "stocks": [
        {"code": "001209", "name": "洪兴股份", "story": "家居龙头+三胎概念+..."}
      ]
    }
  ]
}

code 可空；若提供则与同日 limit_pool/kaipanla 校验唯一名命中后写 matched，
否则 unresolved。不写 theme/themes。
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from ultraboard.ths.stories import load_day  # noqa: E402

STORY_DIR = ROOT / "data" / "ths" / "stories"
LIMIT_DIR = ROOT / "data" / "ths" / "limit_pool"
KPL_DIR = ROOT / "data" / "kaipanla" / "raw"
SOURCE = "tonghuashun_strong_wind_headlines"


def _pool_maps(day: str) -> tuple[dict[str, str], dict[str, str]]:
    """code->name, name->code（name 唯一时才入表）。"""
    code_to_name: dict[str, str] = {}
    name_counts: dict[str, list[str]] = {}
    limit_path = LIMIT_DIR / f"{day}.json"
    if limit_path.exists():
        payload = json.loads(limit_path.read_text(encoding="utf-8-sig"))
        for row in payload.get("stocks") or []:
            code = str(row.get("code") or "").zfill(6)
            name = str(row.get("name") or "").strip()
            if code.isdigit() and name:
                code_to_name[code] = name
                name_counts.setdefault(name, []).append(code)
    kpl_path = KPL_DIR / day / "zt_pool.json"
    if kpl_path.exists():
        payload = json.loads(kpl_path.read_text(encoding="utf-8-sig"))
        for row in payload.get("stocks") or []:
            code = str(row.get("code") or "").zfill(6)
            name = str(row.get("name") or "").strip()
            if code.isdigit() and name and code not in code_to_name:
                code_to_name[code] = name
                name_counts.setdefault(name, []).append(code)
    name_to_code = {
        name: codes[0] for name, codes in name_counts.items() if len(set(codes)) == 1
    }
    return code_to_name, name_to_code


def _source_image(day: str) -> str:
    y, m, _ = day.split("-")
    compact = day.replace("-", "")
    rel = f"data/ths/strong_wind_images/{y}-{m}/{compact}.png"
    if not (ROOT / rel).exists():
        raise FileNotFoundError(f"原图不存在: {rel}")
    return rel


def build_payload(day: str, stories_in: list[dict[str, Any]]) -> dict[str, Any]:
    code_to_name, name_to_code = _pool_maps(day)
    stories: list[dict[str, Any]] = []
    for idx, item in enumerate(stories_in, 1):
        context = str(item.get("context") or "").strip()
        story = str(item.get("story") or "").strip()
        if not context or not story:
            raise ValueError(f"#{idx} 缺少 context/story")
        entry: dict[str, Any] = {
            "source_position": idx,
            "story": story,
            "context": context,
            "headline": f"{context}：{story}",
        }
        stocks_in = item.get("stocks") or []
        if stocks_in:
            stocks_out: list[dict[str, Any]] = []
            for s_idx, stock in enumerate(stocks_in, 1):
                name = str(stock.get("name") or "").strip()
                stock_story = str(stock.get("story") or "").strip()
                if not name or not stock_story:
                    raise ValueError(f"#{idx} stock#{s_idx} 缺 name/story")
                raw_code = stock.get("code")
                code: str | None
                if raw_code in (None, ""):
                    code = name_to_code.get(name)
                else:
                    code = str(raw_code).zfill(6)
                if code and code in code_to_name:
                    # 名码冲突时降为 unresolved
                    if code_to_name[code] != name and name_to_code.get(name) != code:
                        mapped_code = name_to_code.get(name)
                        if mapped_code:
                            code = mapped_code
                            status = "matched_same_day_stock"
                        else:
                            code = None
                            status = "unresolved"
                    else:
                        status = "matched_same_day_stock"
                elif name in name_to_code:
                    code = name_to_code[name]
                    status = "matched_same_day_stock"
                else:
                    code = None
                    status = "unresolved"
                stocks_out.append(
                    {
                        "stock_position": s_idx,
                        "code": code,
                        "name": name,
                        "story": stock_story,
                        "mapping_status": status,
                    }
                )
            entry["stocks"] = stocks_out
        stories.append(entry)
    return {
        "date": day,
        "source": SOURCE,
        "source_image": _source_image(day),
        "stories": stories,
    }


def write_day(day: str, stories_in: list[dict[str, Any]]) -> Path:
    payload = build_payload(day, stories_in)
    path = STORY_DIR / f"{day}.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    load_day(day)
    return path


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="写入单日同花顺故事契约文件")
    parser.add_argument("day", help="YYYY-MM-DD")
    parser.add_argument("--payload", required=True, help="含 stories 的 JSON 路径")
    args = parser.parse_args(argv)
    data = json.loads(Path(args.payload).read_text(encoding="utf-8-sig"))
    stories = data.get("stories")
    if not isinstance(stories, list) or not stories:
        raise SystemExit("payload.stories 必须是非空数组")
    path = write_day(args.day, stories)
    print("wrote", path.as_posix(), "stories", len(stories))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
