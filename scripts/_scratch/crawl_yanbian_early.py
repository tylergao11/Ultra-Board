from __future__ import annotations

import argparse
import concurrent.futures
import html
import json
import math
import re
import threading
import time
from datetime import datetime
from pathlib import Path
from typing import Any

import requests
from bs4 import BeautifulSoup


USER_ID = 5_894_557
USER_NAME = "延边刺客"
LIST_URL = "https://m.tgb.cn/mBlogTopicAjax"
TOPIC_URL = "https://m.tgb.cn/a/{new_topic_id}"
USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/140.0.0.0 Safari/537.36"
)
KEYWORDS = (
    "节点",
    "名称",
    "名字",
    "让位",
    "主动性",
    "带动性",
    "带动",
    "布局",
    "梯队",
    "主升",
    "地域",
    "拼音",
    "字母",
    "代码",
    "指引",
    "陪跑",
    "接力",
    "溢价",
    "发酵",
    "高低切",
    "辨识度",
    "避不开",
    "超预期",
)

_thread_local = threading.local()


def session() -> requests.Session:
    current = getattr(_thread_local, "session", None)
    if current is None:
        current = requests.Session()
        current.headers.update({"User-Agent": USER_AGENT, "Accept-Language": "zh-CN,zh;q=0.9"})
        _thread_local.session = current
    return current


def get_text(url: str, *, params: dict[str, Any] | None = None) -> str:
    last_error: Exception | None = None
    for attempt in range(6):
        try:
            response = session().get(url, params=params, timeout=30)
            if response.status_code == 200 and len(response.content) > 1_000:
                response.encoding = response.apparent_encoding or "utf-8"
                return response.text
            last_error = RuntimeError(
                f"HTTP {response.status_code}, {len(response.content)} bytes: {response.url}"
            )
        except requests.RequestException as exc:
            last_error = exc
        time.sleep(min(4.0, 0.35 * (2**attempt)))
    raise RuntimeError(f"Failed after retries: {url}: {last_error}")


def get_json(url: str, *, params: dict[str, Any]) -> dict[str, Any]:
    last_error: Exception | None = None
    for attempt in range(6):
        try:
            response = session().get(url, params=params, timeout=30)
            if response.status_code == 200:
                return response.json()
            last_error = RuntimeError(f"HTTP {response.status_code}: {response.url}")
        except (requests.RequestException, ValueError) as exc:
            last_error = exc
        time.sleep(min(4.0, 0.35 * (2**attempt)))
    raise RuntimeError(f"Failed after retries: {url}: {last_error}")


def clean_text(value: str) -> str:
    value = html.unescape(value or "")
    value = BeautifulSoup(value, "html.parser").get_text(" ", strip=True)
    value = value.replace("\xa0", " ")
    return re.sub(r"[ \t\r\f\v]+", " ", value).strip()


def clean_main_text(node: Any) -> str:
    if node is None:
        return ""
    lines = [re.sub(r"[ \t\r\f\v]+", " ", line).strip() for line in node.get_text("\n").splitlines()]
    return "\n".join(line for line in lines if line)


def normalize_reply_date(raw: str) -> str:
    raw = clean_text(raw)
    for fmt in ("%y-%m-%d %H:%M", "%Y-%m-%d %H:%M"):
        try:
            return datetime.strptime(raw, fmt).strftime("%Y-%m-%d %H:%M:00")
        except ValueError:
            pass
    return raw


def fetch_metadata(workers: int) -> list[dict[str, Any]]:
    first = get_json(
        LIST_URL,
        params={"userID": USER_ID, "sortFlag": "W", "pageNo": 1},
    )["dto"]
    page_count = int(first["pageNum"])

    def fetch_page(page_no: int) -> list[dict[str, Any]]:
        dto = get_json(
            LIST_URL,
            params={"userID": USER_ID, "sortFlag": "W", "pageNo": page_no},
        )["dto"]
        return dto.get("listTopic") or []

    topics = list(first.get("listTopic") or [])
    with concurrent.futures.ThreadPoolExecutor(max_workers=min(workers, page_count)) as executor:
        for page_topics in executor.map(fetch_page, range(2, page_count + 1)):
            topics.extend(page_topics)

    unique = {int(topic["topicID"]): topic for topic in topics}
    return sorted(unique.values(), key=lambda item: (item["postDate"], int(item["topicID"])))


def page_url(new_topic_id: str, page_no: int) -> str:
    base = TOPIC_URL.format(new_topic_id=new_topic_id)
    return base if page_no == 1 else f"{base}-{page_no}?type="


def parse_replies(soup: BeautifulSoup, page_no: int) -> list[dict[str, Any]]:
    replies: list[dict[str, Any]] = []
    for position, item in enumerate(soup.select(".plItem")):
        meta = item.find(attrs={"contentid": True, "userid": True})
        if meta is None:
            continue
        reply_id = str(meta.get("contentid") or "")
        user_id = str(meta.get("userid") or "")
        body_node = item.select_one(".pl_text")
        body = clean_text(str(meta.get("subject") or ""))
        if not body and body_node is not None:
            body = clean_text(body_node.get_text(" ", strip=True))
        date_node = item.select_one(".pl_time")
        likes_node = item.select_one(".plzan_num")
        replies.append(
            {
                "reply_id": reply_id,
                "user_id": int(user_id) if user_id.isdigit() else user_id,
                "user_name": clean_text(str(meta.get("username") or "")),
                "reply_date": normalize_reply_date(date_node.get_text(" ", strip=True) if date_node else ""),
                "body": body,
                "likes": int(likes_node.get_text(strip=True))
                if likes_node and likes_node.get_text(strip=True).isdigit()
                else None,
                "page_no": page_no,
                "position_on_page": position,
            }
        )
    return replies


def parse_topic_page(html_text: str, new_topic_id: str, page_no: int) -> dict[str, Any]:
    soup = BeautifulSoup(html_text, "html.parser")
    main_node = soup.select_one(".tzitem_text") if page_no == 1 else None
    observed_pages = [1]
    prefix = f"/a/{new_topic_id}-"
    for link in soup.select("a[href]"):
        href = str(link.get("href") or "")
        if href.startswith(prefix):
            match = re.match(rf"^/a/{re.escape(new_topic_id)}-(\d+)", href)
            if match:
                observed_pages.append(int(match.group(1)))
    return {
        "main_text": clean_main_text(main_node),
        "observed_page_count": max(observed_pages),
        "replies": parse_replies(soup, page_no),
    }


def load_existing(path: Path) -> dict[int, dict[str, Any]]:
    if not path.exists():
        return {}
    records: dict[int, dict[str, Any]] = {}
    with path.open("r", encoding="utf-8") as handle:
        for line in handle:
            if line.strip():
                record = json.loads(line)
                records[int(record["topic_id"])] = record
    return records


def keyword_counts(main_text: str, author_replies: list[dict[str, Any]]) -> dict[str, int]:
    corpus = main_text + "\n" + "\n".join(reply["body"] for reply in author_replies)
    return {keyword: corpus.count(keyword) for keyword in KEYWORDS if keyword in corpus}


def enrich_author_replies(replies: list[dict[str, Any]]) -> list[dict[str, Any]]:
    replies = sorted(replies, key=lambda item: (item["page_no"], item["position_on_page"]))
    author_replies: list[dict[str, Any]] = []
    for index, reply in enumerate(replies):
        if reply["user_id"] != USER_ID:
            continue
        enriched = dict(reply)
        if index > 0:
            enriched["newer_neighbor"] = replies[index - 1]
        if index + 1 < len(replies):
            enriched["older_neighbor"] = replies[index + 1]
        author_replies.append(enriched)
    return sorted(author_replies, key=lambda item: (item["reply_date"], item["reply_id"]))


def build_topic_record(
    topic: dict[str, Any],
    rank: int,
    page_count: int,
    pages: dict[int, dict[str, Any]],
    errors: list[dict[str, Any]],
) -> dict[str, Any]:
    new_topic_id = str(topic["newTopicID"]).lstrip("/")
    replies_by_id: dict[str, dict[str, Any]] = {}
    for page_no in sorted(pages):
        for reply in pages[page_no]["replies"]:
            replies_by_id[reply["reply_id"]] = reply
    replies = list(replies_by_id.values())
    author_replies = enrich_author_replies(replies)
    main_text = pages.get(1, {}).get("main_text", "")
    return {
        "chronological_rank": rank,
        "topic_id": int(topic["topicID"]),
        "new_topic_id": new_topic_id,
        "subject": clean_text(str(topic.get("subject") or "")),
        "post_date": topic["postDate"],
        "total_reply_num_reported": int(topic.get("totalReplyNum") or 0),
        "total_view_num_reported": int(topic.get("totalViewNum") or 0),
        "url": TOPIC_URL.format(new_topic_id=new_topic_id),
        "main_text": main_text,
        "main_text_chars": len(main_text),
        "reply_pages_expected": page_count,
        "reply_pages_fetched": len(pages),
        "reply_page_errors": sorted(errors, key=lambda item: item["page_no"]),
        "replies_scraped": len(replies),
        "author_reply_count": len(author_replies),
        "author_replies": author_replies,
        "keyword_counts": keyword_counts(main_text, author_replies),
    }


def write_jsonl(path: Path, records: list[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    with temporary.open("w", encoding="utf-8", newline="\n") as handle:
        for record in records:
            handle.write(json.dumps(record, ensure_ascii=False, separators=(",", ":")) + "\n")
    temporary.replace(path)


def main() -> None:
    parser = argparse.ArgumentParser(description="抓取延边刺客按发表时间排序的最早 N 篇主帖及楼主回复。")
    parser.add_argument("--count", type=int, default=200)
    parser.add_argument("--workers", type=int, default=20)
    parser.add_argument(
        "--output",
        type=Path,
        default=Path("data/research/layout_puzzle/yanbian_cike_early.jsonl"),
    )
    args = parser.parse_args()
    if args.count < 1:
        raise SystemExit("--count 必须大于 0")

    topics = fetch_metadata(args.workers)
    selected = topics[: args.count]
    if len(selected) < args.count:
        raise SystemExit(f"只发现 {len(selected)} 篇，少于请求的 {args.count} 篇")

    existing = load_existing(args.output)
    records: dict[int, dict[str, Any]] = {}
    for rank, topic in enumerate(selected, start=1):
        topic_id = int(topic["topicID"])
        old = existing.get(topic_id)
        if old and old.get("main_text") and not old.get("reply_page_errors"):
            old["chronological_rank"] = rank
            records[topic_id] = old

    pending = [
        (rank, topic)
        for rank, topic in enumerate(selected, start=1)
        if int(topic["topicID"]) not in records
    ]
    print(
        f"metadata={len(topics)} selected={len(selected)} reused={len(records)} "
        f"pending={len(pending)} range={selected[0]['postDate']}..{selected[-1]['postDate']}",
        flush=True,
    )

    pending_by_id = {int(topic["topicID"]): (rank, topic) for rank, topic in pending}
    expected_pages = {
        topic_id: max(1, math.ceil(int(topic.get("totalReplyNum") or 0) / 10))
        for topic_id, (_, topic) in pending_by_id.items()
    }
    page_results: dict[int, dict[int, dict[str, Any]]] = {topic_id: {} for topic_id in pending_by_id}
    page_errors: dict[int, list[dict[str, Any]]] = {topic_id: [] for topic_id in pending_by_id}
    tasks = [
        (topic_id, str(topic["newTopicID"]).lstrip("/"), page_no)
        for topic_id, (_, topic) in pending_by_id.items()
        for page_no in range(1, expected_pages[topic_id] + 1)
    ]

    def fetch_page_task(task: tuple[int, str, int]) -> tuple[int, int, dict[str, Any]]:
        topic_id, new_topic_id, page_no = task
        page_html = get_text(page_url(new_topic_id, page_no))
        return topic_id, page_no, parse_topic_page(page_html, new_topic_id, page_no)

    started = time.monotonic()
    with concurrent.futures.ThreadPoolExecutor(max_workers=args.workers) as executor:
        futures = {executor.submit(fetch_page_task, task): task for task in tasks}
        for completed, future in enumerate(concurrent.futures.as_completed(futures), start=1):
            topic_id, _, page_no = futures[future]
            try:
                fetched_topic_id, fetched_page_no, parsed = future.result()
                page_results[fetched_topic_id][fetched_page_no] = parsed
            except Exception as exc:  # The manifest retains exact missing pages for a targeted retry.
                page_errors[topic_id].append({"page_no": page_no, "error": str(exc)})
            if completed % 100 == 0 or completed == len(tasks):
                elapsed = max(time.monotonic() - started, 0.001)
                print(
                    f"pages={completed}/{len(tasks)} rate={completed / elapsed:.1f}/s errors="
                    f"{sum(len(value) for value in page_errors.values())}",
                    flush=True,
                )

    for topic_id, (rank, topic) in pending_by_id.items():
        records[topic_id] = build_topic_record(
            topic,
            rank,
            expected_pages[topic_id],
            page_results[topic_id],
            page_errors[topic_id],
        )

    ordered = sorted(records.values(), key=lambda item: item["chronological_rank"])
    write_jsonl(args.output, ordered)
    manifest_path = args.output.with_name(args.output.stem + "_manifest.json")
    manifest = {
        "source": f"https://www.tgb.cn/blog/{USER_ID}",
        "mobile_list_endpoint": LIST_URL,
        "user_id": USER_ID,
        "user_name": USER_NAME,
        "selection": "earliest_posts_chronological",
        "topic_count": len(ordered),
        "first_post_date": ordered[0]["post_date"],
        "last_post_date": ordered[-1]["post_date"],
        "main_text_chars": sum(item["main_text_chars"] for item in ordered),
        "reply_pages_expected": sum(item["reply_pages_expected"] for item in ordered),
        "reply_pages_fetched": sum(item["reply_pages_fetched"] for item in ordered),
        "author_reply_count": sum(item["author_reply_count"] for item in ordered),
        "topics_with_errors": [
            {"topic_id": item["topic_id"], "errors": item["reply_page_errors"]}
            for item in ordered
            if item["reply_page_errors"]
        ],
        "output": str(args.output).replace("\\", "/"),
    }
    manifest_path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(manifest, ensure_ascii=False), flush=True)


if __name__ == "__main__":
    main()
