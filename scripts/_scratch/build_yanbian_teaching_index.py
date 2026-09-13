from __future__ import annotations

import json
import re
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any


SOURCE = Path("data/research/layout_puzzle/yanbian_cike_timeline_main.jsonl")
INDEX_OUTPUT = Path("data/research/layout_puzzle/yanbian_cike_teaching_sentence_index.jsonl")
STATS_OUTPUT = Path("data/research/layout_puzzle/yanbian_cike_teaching_trajectory.json")

TERM_GROUPS = {
    "节点": ("节点", "断板日", "冰点", "转折点", "破局日", "出生日", "出生"),
    "名称": ("名字", "名称", "字辈", "拼音", "字母", "代码", "地名", "地域", "同音", "谐音", "数字股"),
    "让位": ("让位", "退位", "挡刀", "压制", "身位", "卡位", "反推", "腾出", "故意让"),
    "主动性": ("主动性", "主动", "独立", "脱离", "率先", "被带动", "跟随", "借力"),
    "带动性": ("带动性", "带动", "发酵", "助力", "小弟", "梯队", "首板供应", "扩散"),
    "布局": ("布局", "主控", "量化", "语料", "工具人", "左右手", "配套", "伴生", "陪跑", "做局", "一伙"),
    "接力": ("接力", "补涨", "主升", "高低切", "溢价", "预期"),
}
EXPLANATION_MARKERS = (
    "因为",
    "所以",
    "说明",
    "如果",
    "否则",
    "不是",
    "而是",
    "本质",
    "定义",
    "为何",
    "为什么",
    "怎么",
    "就是",
    "只有",
    "前提",
    "意味着",
    "反推",
    "区别",
    "同理",
    "比如",
)
NOISE_MARKERS = ("打赏", "取关", "粉丝", "晒单", "收益截图", "账户", "比赛", "吹牛")


def sentences(text: str) -> list[str]:
    pieces = re.split(r"(?<=[。！？!?；;])|\n+", text)
    return [re.sub(r"\s+", " ", piece).strip() for piece in pieces if piece.strip()]


def groups_for(text: str) -> dict[str, list[str]]:
    return {
        group: [term for term in terms if term in text]
        for group, terms in TERM_GROUPS.items()
        if any(term in text for term in terms)
    }


def period(post_date: str) -> str:
    year = int(post_date[:4])
    month = int(post_date[5:7])
    quarter = (month - 1) // 3 + 1
    return f"{year}-Q{quarter}"


def main() -> None:
    topics = [json.loads(line) for line in SOURCE.read_text(encoding="utf-8").splitlines() if line]
    indexed: list[dict[str, Any]] = []
    period_counts: dict[str, Counter[str]] = defaultdict(Counter)
    period_posts: Counter[str] = Counter()
    first_occurrences: dict[str, dict[str, Any]] = {}
    post_scores: list[dict[str, Any]] = []

    for topic in topics:
        topic_period = period(topic["post_date"])
        period_posts[topic_period] += 1
        topic_group_counts: Counter[str] = Counter()
        evidence_count = 0
        for sentence_no, sentence in enumerate(sentences(topic["main_text"]), start=1):
            matched = groups_for(sentence)
            if not matched:
                continue
            explanation_count = sum(marker in sentence for marker in EXPLANATION_MARKERS)
            noise_count = sum(marker in sentence for marker in NOISE_MARKERS)
            teaching_score = (
                len(matched) * 3
                + sum(min(len(terms), 3) for terms in matched.values())
                + min(explanation_count, 3) * 2
                - noise_count * 2
            )
            record = {
                "topic_rank": topic["chronological_rank"],
                "topic_id": topic["topic_id"],
                "post_date": topic["post_date"],
                "period": topic_period,
                "subject": topic["subject"],
                "url": topic["url"],
                "sentence_no": sentence_no,
                "groups": matched,
                "explanation_markers": [marker for marker in EXPLANATION_MARKERS if marker in sentence],
                "teaching_score": teaching_score,
                "text": sentence,
            }
            indexed.append(record)
            for group, terms in matched.items():
                topic_group_counts[group] += len(terms)
                period_counts[topic_period][group] += len(terms)
                for term in terms:
                    first_occurrences.setdefault(
                        term,
                        {
                            "topic_rank": topic["chronological_rank"],
                            "post_date": topic["post_date"],
                            "subject": topic["subject"],
                            "url": topic["url"],
                            "text": sentence,
                        },
                    )
            if teaching_score >= 9:
                evidence_count += 1

        breadth = sum(1 for count in topic_group_counts.values() if count)
        post_scores.append(
            {
                "topic_rank": topic["chronological_rank"],
                "topic_id": topic["topic_id"],
                "post_date": topic["post_date"],
                "period": topic_period,
                "subject": topic["subject"],
                "url": topic["url"],
                "group_counts": dict(topic_group_counts),
                "concept_breadth": breadth,
                "high_value_sentence_count": evidence_count,
                "teaching_score": sum(topic_group_counts.values()) + breadth * 3 + evidence_count * 2,
            }
        )

    write_tmp = INDEX_OUTPUT.with_suffix(INDEX_OUTPUT.suffix + ".tmp")
    with write_tmp.open("w", encoding="utf-8", newline="\n") as handle:
        for record in indexed:
            handle.write(json.dumps(record, ensure_ascii=False, separators=(",", ":")) + "\n")
    write_tmp.replace(INDEX_OUTPUT)

    top_by_period: dict[str, list[dict[str, Any]]] = {}
    for key in sorted(period_posts):
        candidates = [item for item in post_scores if item["period"] == key]
        candidates.sort(key=lambda item: (-item["teaching_score"], item["topic_rank"]))
        top_by_period[key] = candidates[:15]

    stats = {
        "source": str(SOURCE).replace("\\", "/"),
        "topic_count": len(topics),
        "indexed_sentence_count": len(indexed),
        "term_groups": TERM_GROUPS,
        "periods": {
            key: {"post_count": period_posts[key], "term_counts": dict(period_counts[key])}
            for key in sorted(period_posts)
        },
        "first_occurrences": first_occurrences,
        "top_teaching_posts_by_period": top_by_period,
    }
    STATS_OUTPUT.write_text(json.dumps(stats, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(
        json.dumps(
            {
                "topic_count": len(topics),
                "indexed_sentence_count": len(indexed),
                "period_count": len(period_posts),
                "index_output": str(INDEX_OUTPUT).replace("\\", "/"),
                "stats_output": str(STATS_OUTPUT).replace("\\", "/"),
            },
            ensure_ascii=False,
        )
    )


if __name__ == "__main__":
    main()
