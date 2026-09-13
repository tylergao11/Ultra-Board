from __future__ import annotations

import argparse
import concurrent.futures
import json
import math
import time
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any

from crawl_yanbian_early import (
    KEYWORDS,
    TOPIC_URL,
    USER_ID,
    USER_NAME,
    enrich_author_replies,
    fetch_metadata,
    get_text,
    page_url,
    parse_topic_page,
    write_jsonl,
)


def read_jsonl(path: Path) -> list[dict[str, Any]]:
    if not path.exists():
        return []
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]


def main_record(
    topic: dict[str, Any],
    rank: int,
    main_text: str,
    text_source: str = "mobile_topic_html",
) -> dict[str, Any]:
    return {
        "chronological_rank": rank,
        "topic_id": int(topic["topicID"]),
        "new_topic_id": str(topic["newTopicID"]).lstrip("/"),
        "subject": topic.get("subject") or "",
        "post_date": topic["postDate"],
        "total_reply_num_reported": int(topic.get("totalReplyNum") or 0),
        "total_view_num_reported": int(topic.get("totalViewNum") or 0),
        "url": TOPIC_URL.format(new_topic_id=str(topic["newTopicID"]).lstrip("/")),
        "main_text": main_text,
        "main_text_chars": len(main_text),
        "main_text_source": text_source,
        "keyword_counts": {keyword: main_text.count(keyword) for keyword in KEYWORDS if keyword in main_text},
    }


def sample_pages(page_count: int, edge_pages: int, strata: int) -> set[int]:
    if page_count <= edge_pages * 2 + strata:
        return set(range(1, page_count + 1))
    selected = {1, 2}
    selected.update(range(max(1, page_count - edge_pages + 1), page_count + 1))
    if strata > 1:
        selected.update(
            round(1 + index * (page_count - 1) / (strata - 1))
            for index in range(strata)
        )
    return {page for page in selected if 1 <= page <= page_count}


def reply_temporality(topic_date: str, reply_date: str) -> str:
    try:
        topic_dt = datetime.fromisoformat(topic_date)
        reply_dt = datetime.fromisoformat(reply_date)
    except ValueError:
        return "unknown"
    if reply_dt < topic_dt - timedelta(days=1):
        return "date_anomaly"
    if reply_dt <= topic_dt + timedelta(days=7):
        return "contemporaneous_7d"
    if reply_dt <= topic_dt + timedelta(days=45):
        return "near_term_45d"
    return "later_revisit"


def decorate_reply(
    reply: dict[str, Any],
    topic: dict[str, Any],
    rank: int,
    sampling_source: str,
) -> dict[str, Any]:
    item = dict(reply)
    item.update(
        {
            "topic_rank": rank,
            "topic_id": int(topic["topicID"]),
            "new_topic_id": str(topic["newTopicID"]).lstrip("/"),
            "topic_subject": topic.get("subject") or "",
            "topic_post_date": topic["postDate"],
            "topic_url": TOPIC_URL.format(new_topic_id=str(topic["newTopicID"]).lstrip("/")),
            "sampling_sources": [sampling_source],
            "reply_temporality": reply_temporality(topic["postDate"], item.get("reply_date") or ""),
            "irony_risk_period": (item.get("reply_date") or "") >= "2025-01-01",
        }
    )
    return item


def merge_reply(target: dict[str, dict[str, Any]], reply: dict[str, Any]) -> None:
    reply_id = str(reply.get("reply_id") or "")
    if not reply_id:
        return
    old = target.get(reply_id)
    if old is None:
        target[reply_id] = reply
        return
    old["sampling_sources"] = sorted(set(old.get("sampling_sources") or []) | set(reply.get("sampling_sources") or []))
    for neighbor in ("older_neighbor", "newer_neighbor"):
        if not old.get(neighbor) and reply.get(neighbor):
            old[neighbor] = reply[neighbor]


def main() -> None:
    parser = argparse.ArgumentParser(description="抓取延边刺客 2023 年至今公开主帖全文与分层回复样本。")
    parser.add_argument("--workers", type=int, default=24)
    parser.add_argument("--edge-pages", type=int, default=12)
    parser.add_argument("--strata", type=int, default=12)
    parser.add_argument("--full-through-date", default="2023-12-31")
    parser.add_argument("--skip-replies", action="store_true")
    parser.add_argument(
        "--main-output",
        type=Path,
        default=Path("data/research/layout_puzzle/yanbian_cike_timeline_main.jsonl"),
    )
    parser.add_argument(
        "--reply-output",
        type=Path,
        default=Path("data/research/layout_puzzle/yanbian_cike_timeline_author_replies.jsonl"),
    )
    parser.add_argument(
        "--page-cache",
        type=Path,
        default=Path("data/research/layout_puzzle/yanbian_cike_timeline_reply_page_cache.jsonl"),
    )
    parser.add_argument(
        "--early-seed",
        type=Path,
        default=Path("data/research/layout_puzzle/yanbian_cike_early.jsonl"),
    )
    args = parser.parse_args()

    topics = fetch_metadata(args.workers)
    topic_by_id = {int(topic["topicID"]): topic for topic in topics}
    rank_by_id = {int(topic["topicID"]): rank for rank, topic in enumerate(topics, start=1)}
    print(
        f"public_topics={len(topics)} range={topics[0]['postDate']}..{topics[-1]['postDate']}",
        flush=True,
    )

    existing_main = {int(item["topic_id"]): item for item in read_jsonl(args.main_output)}
    early_seed = {int(item["topic_id"]): item for item in read_jsonl(args.early_seed)}
    main_records: dict[int, dict[str, Any]] = {}
    for topic_id, topic in topic_by_id.items():
        rank = rank_by_id[topic_id]
        old = existing_main.get(topic_id)
        if old and old.get("main_text"):
            old["chronological_rank"] = rank
            old.setdefault("main_text_source", "mobile_topic_html")
            main_records[topic_id] = old
            continue
        seed = early_seed.get(topic_id)
        if seed and seed.get("main_text"):
            main_records[topic_id] = main_record(topic, rank, seed["main_text"], "early_full_crawl")

    missing_main = [
        (int(topic["topicID"]), str(topic["newTopicID"]).lstrip("/"))
        for topic in topics
        if int(topic["topicID"]) not in main_records
    ]
    print(f"main_reused={len(main_records)} main_pending={len(missing_main)}", flush=True)

    def fetch_main(task: tuple[int, str]) -> tuple[int, str, str]:
        topic_id, new_topic_id = task
        parsed = parse_topic_page(get_text(page_url(new_topic_id, 1)), new_topic_id, 1)
        if not parsed["main_text"]:
            excerpt = str(topic_by_id[topic_id].get("content") or "").strip()
            if excerpt:
                return topic_id, excerpt, "profile_excerpt_non_text_or_image_post"
            raise RuntimeError(f"empty main text: topic_id={topic_id}")
        return topic_id, parsed["main_text"], "mobile_topic_html"

    main_errors: list[dict[str, Any]] = []
    with concurrent.futures.ThreadPoolExecutor(max_workers=args.workers) as executor:
        futures = {executor.submit(fetch_main, task): task for task in missing_main}
        for completed, future in enumerate(concurrent.futures.as_completed(futures), start=1):
            topic_id, _ = futures[future]
            try:
                fetched_topic_id, main_text, text_source = future.result()
                main_records[fetched_topic_id] = main_record(
                    topic_by_id[fetched_topic_id], rank_by_id[fetched_topic_id], main_text, text_source
                )
            except Exception as exc:
                main_errors.append({"topic_id": topic_id, "error": str(exc)})
            if completed % 100 == 0 or completed == len(missing_main):
                print(f"main={completed}/{len(missing_main)} errors={len(main_errors)}", flush=True)

    ordered_main = sorted(main_records.values(), key=lambda item: item["chronological_rank"])
    write_jsonl(args.main_output, ordered_main)
    if main_errors:
        raise RuntimeError(f"main post failures: {main_errors[:5]}")

    if args.skip_replies:
        manifest = {
            "source": f"https://www.tgb.cn/blog/{USER_ID}",
            "user_id": USER_ID,
            "user_name": USER_NAME,
            "public_topic_count": len(ordered_main),
            "first_post_date": ordered_main[0]["post_date"],
            "last_post_date": ordered_main[-1]["post_date"],
            "main_text_chars": sum(item["main_text_chars"] for item in ordered_main),
            "non_html_text_topics": [
                {
                    "topic_id": item["topic_id"],
                    "subject": item["subject"],
                    "source": item["main_text_source"],
                }
                for item in ordered_main
                if item["main_text_source"] != "mobile_topic_html"
                and item["main_text_source"] != "early_full_crawl"
            ],
            "reply_sampling": "skipped_by_request_priority",
            "outputs": {"main": str(args.main_output).replace("\\", "/")},
        }
        manifest_path = args.main_output.with_name("yanbian_cike_timeline_manifest.json")
        manifest_path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        print(json.dumps(manifest, ensure_ascii=False), flush=True)
        return

    # Seed the reply corpus with the already complete earliest-200 crawl.
    replies_by_id: dict[str, dict[str, Any]] = {}
    for topic_id, seed in early_seed.items():
        topic = topic_by_id.get(topic_id)
        if topic is None:
            continue
        rank = rank_by_id[topic_id]
        for reply in seed.get("author_replies") or []:
            merge_reply(replies_by_id, decorate_reply(reply, topic, rank, "full_early_seed"))

    cached_pages: dict[str, dict[str, Any]] = {}
    for item in read_jsonl(args.page_cache):
        cached_pages[item["page_key"]] = item

    page_tasks: list[dict[str, Any]] = []
    for rank, topic in enumerate(topics, start=1):
        topic_id = int(topic["topicID"])
        if topic_id in early_seed:
            continue
        new_topic_id = str(topic["newTopicID"]).lstrip("/")
        page_count = max(1, math.ceil(int(topic.get("totalReplyNum") or 0) / 10))
        if topic["postDate"][:10] <= args.full_through_date:
            selected_pages = set(range(1, page_count + 1))
            sampling_source = "full_2023"
        else:
            selected_pages = sample_pages(page_count, args.edge_pages, args.strata)
            sampling_source = "timeline_stratified"
        for page_no in sorted(selected_pages):
            page_key = f"{topic_id}:normal:{page_no}"
            page_tasks.append(
                {
                    "page_key": page_key,
                    "topic_id": topic_id,
                    "rank": rank,
                    "new_topic_id": new_topic_id,
                    "page_no": page_no,
                    "variant": "normal",
                    "sampling_source": sampling_source,
                }
            )
        hot_key = f"{topic_id}:hot:1"
        page_tasks.append(
            {
                "page_key": hot_key,
                "topic_id": topic_id,
                "rank": rank,
                "new_topic_id": new_topic_id,
                "page_no": 1,
                "variant": "hot",
                "sampling_source": "hot_replies",
            }
        )

    pending_pages = [task for task in page_tasks if task["page_key"] not in cached_pages]
    print(
        f"reply_pages_selected={len(page_tasks)} cached={len(page_tasks) - len(pending_pages)} "
        f"pending={len(pending_pages)}",
        flush=True,
    )

    def fetch_reply_page(task: dict[str, Any]) -> dict[str, Any]:
        if task["variant"] == "hot":
            url = TOPIC_URL.format(new_topic_id=task["new_topic_id"]) + "-1?type=Z"
        else:
            url = page_url(task["new_topic_id"], int(task["page_no"]))
        parsed = parse_topic_page(get_text(url), task["new_topic_id"], int(task["page_no"]))
        author_replies = enrich_author_replies(parsed["replies"])
        return {
            "page_key": task["page_key"],
            "topic_id": task["topic_id"],
            "rank": task["rank"],
            "page_no": task["page_no"],
            "variant": task["variant"],
            "sampling_source": task["sampling_source"],
            "reply_count_on_page": len(parsed["replies"]),
            "author_replies": author_replies,
        }

    args.page_cache.parent.mkdir(parents=True, exist_ok=True)
    reply_errors: list[dict[str, Any]] = []
    started = time.monotonic()
    with args.page_cache.open("a", encoding="utf-8", newline="\n") as cache_handle:
        with concurrent.futures.ThreadPoolExecutor(max_workers=args.workers) as executor:
            futures = {executor.submit(fetch_reply_page, task): task for task in pending_pages}
            for completed, future in enumerate(concurrent.futures.as_completed(futures), start=1):
                task = futures[future]
                try:
                    page_record = future.result()
                    cached_pages[page_record["page_key"]] = page_record
                    cache_handle.write(json.dumps(page_record, ensure_ascii=False, separators=(",", ":")) + "\n")
                except Exception as exc:
                    reply_errors.append({"page_key": task["page_key"], "error": str(exc)})
                if completed % 100 == 0 or completed == len(pending_pages):
                    cache_handle.flush()
                    elapsed = max(time.monotonic() - started, 0.001)
                    print(
                        f"reply_pages={completed}/{len(pending_pages)} "
                        f"rate={completed / elapsed:.1f}/s errors={len(reply_errors)}",
                        flush=True,
                    )

    for task in page_tasks:
        page_record = cached_pages.get(task["page_key"])
        if page_record is None:
            continue
        topic = topic_by_id[int(task["topic_id"])]
        rank = rank_by_id[int(task["topic_id"])]
        for reply in page_record.get("author_replies") or []:
            merge_reply(
                replies_by_id,
                decorate_reply(reply, topic, rank, page_record["sampling_source"]),
            )

    ordered_replies = sorted(
        replies_by_id.values(),
        key=lambda item: (item.get("reply_date") or "", item["topic_rank"], item["reply_id"]),
    )
    write_jsonl(args.reply_output, ordered_replies)
    manifest = {
        "source": f"https://www.tgb.cn/blog/{USER_ID}",
        "user_id": USER_ID,
        "user_name": USER_NAME,
        "public_topic_count": len(ordered_main),
        "first_post_date": ordered_main[0]["post_date"],
        "last_post_date": ordered_main[-1]["post_date"],
        "main_text_chars": sum(item["main_text_chars"] for item in ordered_main),
        "main_errors": main_errors,
        "reply_sampling": {
            "full_through_date": args.full_through_date,
            "edge_pages": args.edge_pages,
            "strata": args.strata,
            "selected_page_count": len(page_tasks),
            "cached_page_count": sum(task["page_key"] in cached_pages for task in page_tasks),
            "errors": reply_errors,
            "author_reply_count": len(ordered_replies),
            "contemporaneous_reply_count": sum(
                item["reply_temporality"] == "contemporaneous_7d" for item in ordered_replies
            ),
            "irony_risk_period_reply_count": sum(item["irony_risk_period"] for item in ordered_replies),
        },
        "outputs": {
            "main": str(args.main_output).replace("\\", "/"),
            "author_replies": str(args.reply_output).replace("\\", "/"),
            "reply_page_cache": str(args.page_cache).replace("\\", "/"),
        },
    }
    manifest_path = args.main_output.with_name("yanbian_cike_timeline_manifest.json")
    manifest_path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(manifest, ensure_ascii=False), flush=True)


if __name__ == "__main__":
    main()
