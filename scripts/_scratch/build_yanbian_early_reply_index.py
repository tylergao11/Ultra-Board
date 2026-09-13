from __future__ import annotations

import json
import re
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any


SOURCE = Path("data/research/layout_puzzle/yanbian_cike_early.jsonl")
INDEX_OUTPUT = Path("data/research/layout_puzzle/yanbian_cike_early_teaching_reply_index.jsonl")
SUMMARY_OUTPUT = Path("data/research/layout_puzzle/yanbian_cike_early_teaching_reply_summary.json")

TERM_GROUPS = {
    "市场资金": ("资金", "增量", "存量", "吸金", "流动性", "容量", "大盘", "指数", "情绪"),
    "题材竞争": ("主线", "题材", "主升", "过渡", "敌对", "伴生", "分支", "避险", "风口", "板块"),
    "时序节点": ("节点", "断板日", "冰点", "转折点", "竞价", "首封", "回封", "午后", "先涨停", "先上板"),
    "梯队空间": ("梯队", "首板供应", "身位", "高标", "中位", "空间", "高度", "三二一", "321"),
    "角色关系": ("龙头", "补涨", "跟风", "先锋", "工具人", "母图", "模仿", "反推", "卡位", "让位"),
    "主动带动": ("主动性", "带动性", "主动", "带动", "独立", "分离", "脱离", "发酵", "助攻"),
    "预期交易": ("预期", "性价比", "买点", "卖点", "接力", "空仓", "试错", "风险", "仓位", "计划"),
    "语言线索": ("名字", "名称", "字辈", "地名", "地域", "数字股", "代码", "谐音", "拼音", "字母"),
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
    "前提",
    "意味着",
    "区别",
    "比如",
    "同理",
    "取决于",
    "反推",
    "原因",
)
QUESTION_MARKERS = ("请教", "怎么", "为什么", "为何", "如何", "意思", "理解", "区别", "？", "?")
LOW_VALUE_PATTERNS = (
    r"^(发财|谢谢|感谢|恭喜|收到|好的|是的|对的|没错|不清楚|不知道|看不懂|哈哈)+[！!。.]?$",
    r"^(赞|前排|打赏|加油|晚安|早安)[！!。.]?$",
)


def normalize(text: str) -> str:
    return re.sub(r"\s+", " ", text or "").strip()


def groups_for(text: str) -> dict[str, list[str]]:
    return {
        group: [term for term in terms if term in text]
        for group, terms in TERM_GROUPS.items()
        if any(term in text for term in terms)
    }


def low_value(text: str) -> bool:
    return any(re.fullmatch(pattern, text) for pattern in LOW_VALUE_PATTERNS)


def question_context(reply: dict[str, Any]) -> dict[str, Any] | None:
    candidates = []
    for relation in ("older_neighbor", "newer_neighbor"):
        neighbor = reply.get(relation) or {}
        body = normalize(neighbor.get("body", ""))
        if not body or neighbor.get("user_id") == 5894557:
            continue
        score = sum(marker in body for marker in QUESTION_MARKERS)
        if score:
            candidates.append((score, relation, neighbor, body))
    if not candidates:
        return None
    _, relation, neighbor, body = max(candidates, key=lambda item: (item[0], len(item[3])))
    return {
        "relation": relation,
        "reply_id": neighbor.get("reply_id"),
        "user_name": neighbor.get("user_name"),
        "reply_date": neighbor.get("reply_date"),
        "body": body,
    }


def main() -> None:
    topics = [json.loads(line) for line in SOURCE.read_text(encoding="utf-8").splitlines() if line]
    records: list[dict[str, Any]] = []
    group_counts: Counter[str] = Counter()
    stage_records: dict[str, list[dict[str, Any]]] = defaultdict(list)
    seen_reply_ids: set[str] = set()

    for topic in topics:
        rank = int(topic["chronological_rank"])
        stage = f"{((rank - 1) // 50) * 50 + 1:03d}-{min(((rank - 1) // 50 + 1) * 50, 300):03d}"
        for reply in topic.get("author_replies") or []:
            reply_id = str(reply.get("reply_id") or "")
            if reply_id in seen_reply_ids:
                continue
            seen_reply_ids.add(reply_id)
            reply_date = str(reply.get("reply_date") or "")
            if reply_date >= "2025-01-01":
                continue
            body = normalize(reply.get("body", ""))
            if len(body) < 8 or low_value(body):
                continue
            matched = groups_for(body)
            if not matched:
                continue
            explanations = [marker for marker in EXPLANATION_MARKERS if marker in body]
            question = question_context(reply)
            breadth = len(matched)
            score = (
                breadth * 4
                + sum(min(len(terms), 3) for terms in matched.values())
                + min(len(explanations), 4) * 2
                + (3 if question else 0)
                + min(int(reply.get("likes") or 0), 10) // 2
                + (2 if 25 <= len(body) <= 500 else 0)
            )
            record = {
                "topic_rank": rank,
                "stage": stage,
                "topic_id": topic["topic_id"],
                "topic_date": topic["post_date"],
                "reply_id": reply_id,
                "reply_date": reply_date,
                "subject": topic["subject"],
                "url": topic["url"],
                "likes": int(reply.get("likes") or 0),
                "groups": matched,
                "explanation_markers": explanations,
                "teaching_score": score,
                "body": body,
                "question_context": question,
            }
            records.append(record)
            stage_records[stage].append(record)
            group_counts.update(matched.keys())

    records.sort(key=lambda item: (item["topic_rank"], item["reply_date"] or "", item["reply_id"]))
    with INDEX_OUTPUT.open("w", encoding="utf-8", newline="\n") as handle:
        for record in records:
            handle.write(json.dumps(record, ensure_ascii=False, separators=(",", ":")) + "\n")

    top_by_stage: dict[str, list[dict[str, Any]]] = {}
    for stage, candidates in sorted(stage_records.items()):
        ordered = sorted(candidates, key=lambda item: (-item["teaching_score"], -item["likes"], item["topic_rank"]))
        top_by_stage[stage] = ordered[:40]

    summary = {
        "source": str(SOURCE).replace("\\", "/"),
        "reply_count_scanned": len(seen_reply_ids),
        "teaching_reply_count": len(records),
        "group_counts": dict(group_counts),
        "top_by_50_topic_stage": top_by_stage,
    }
    SUMMARY_OUTPUT.write_text(json.dumps(summary, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({
        "reply_count_scanned": len(seen_reply_ids),
        "teaching_reply_count": len(records),
        "index_output": str(INDEX_OUTPUT).replace("\\", "/"),
        "summary_output": str(SUMMARY_OUTPUT).replace("\\", "/"),
    }, ensure_ascii=False))


if __name__ == "__main__":
    main()
