from __future__ import annotations

import argparse
import json
import re
from pathlib import Path
from typing import Any


def sentences(text: str) -> list[str]:
    return [
        part.strip()
        for part in re.split(r"(?<=[。！？!?；;])|\n+", text)
        if part.strip()
    ]


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("pattern")
    parser.add_argument("--input", type=Path, default=Path("data/research/layout_puzzle/yanbian_cike_early.jsonl"))
    parser.add_argument("--source", choices=("all", "main", "reply"), default="all")
    parser.add_argument("--limit", type=int, default=80)
    parser.add_argument("--sort", choices=("chronological", "likes"), default="chronological")
    parser.add_argument("--context", type=int, default=0)
    args = parser.parse_args()

    pattern = re.compile(args.pattern, re.IGNORECASE)
    topics = [json.loads(line) for line in args.input.read_text(encoding="utf-8").splitlines() if line]
    matches: list[dict[str, Any]] = []
    for topic in topics:
        if args.source in ("all", "main"):
            parts = sentences(topic["main_text"])
            for index, part in enumerate(parts):
                if pattern.search(part):
                    lo = max(0, index - args.context)
                    hi = min(len(parts), index + args.context + 1)
                    matches.append(
                        {
                            "rank": topic["chronological_rank"],
                            "date": topic["post_date"],
                            "source": "主帖",
                            "likes": -1,
                            "subject": topic["subject"],
                            "url": topic["url"],
                            "text": " / ".join(parts[lo:hi]),
                        }
                    )
        if args.source in ("all", "reply"):
            for reply in topic.get("author_replies") or []:
                if pattern.search(reply["body"]):
                    older = reply.get("older_neighbor") or {}
                    newer = reply.get("newer_neighbor") or {}
                    matches.append(
                        {
                            "rank": topic["chronological_rank"],
                            "date": reply["reply_date"],
                            "source": "回复",
                            "likes": reply.get("likes") or 0,
                            "subject": topic["subject"],
                            "url": topic["url"],
                            "text": reply["body"],
                            "older_neighbor": older.get("body", ""),
                            "newer_neighbor": newer.get("body", ""),
                        }
                    )

    if args.sort == "likes":
        matches.sort(key=lambda item: (-item["likes"], item["date"], item["rank"]))
    else:
        matches.sort(key=lambda item: (item["date"], item["rank"], item["source"]))
    print(f"matches={len(matches)}")
    for match in matches[: args.limit]:
        print(
            f"{match['rank']:03d}|{match['date'][:16]}|{match['source']}|"
            f"赞{match['likes'] if match['likes'] >= 0 else '-'}|{match['subject']}|{match['text'][:600]}"
        )
        if match.get("older_neighbor"):
            print(f"  较早邻句: {match['older_neighbor'][:300]}")
        if match.get("newer_neighbor"):
            print(f"  较晚邻句: {match['newer_neighbor'][:300]}")
        print(f"  {match['url']}")


if __name__ == "__main__":
    main()
