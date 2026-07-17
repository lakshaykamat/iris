"""Choosing what to recall for a turn.

Episodic memories are ranked by recency x importance x keyword relevance — no
embeddings yet (see plan section 5). The top few, together with every active
fact, are rendered into the memory block that goes into the system prompt.
Recalling a memory bumps its `last_recalled` so recency tracks real use.
"""

import re
from datetime import datetime, timezone

from memory.store import TS_FORMAT, Store

RECALL_K = 8
MAX_IMPORTANCE = 10
RECENCY_WEIGHT = 1.0
IMPORTANCE_WEIGHT = 1.0
RELEVANCE_WEIGHT = 2.0

_STOPWORDS = {
    "the", "and", "for", "you", "your", "was", "were", "have", "has", "had",
    "that", "this", "with", "but", "not", "are", "his", "her", "she", "him",
    "they", "them", "about", "just", "like", "will", "would", "what", "when",
}


def _tokens(text: str) -> set[str]:
    words = re.findall(r"[a-z0-9']+", text.lower())
    return {w for w in words if len(w) > 2 and w not in _STOPWORDS}


def _age_days(ts: str, now: datetime) -> float:
    when = datetime.strptime(ts, TS_FORMAT).replace(tzinfo=timezone.utc)
    return max(0.0, (now - when).total_seconds() / 86400)


def _recency(memory, now: datetime) -> float:
    when = memory["last_recalled"] or memory["ts"]
    return 1.0 / (1.0 + _age_days(when, now))


def _relevance(memory, keywords: set[str]) -> float:
    if not keywords:
        return 0.0
    return len(keywords & _tokens(memory["text"])) / len(keywords)


def _score(memory, keywords: set[str], now: datetime) -> float:
    return (
        RECENCY_WEIGHT * _recency(memory, now)
        + IMPORTANCE_WEIGHT * (memory["importance"] / MAX_IMPORTANCE)
        + RELEVANCE_WEIGHT * _relevance(memory, keywords)
    )


def top_k(store: Store, trigger: str, k: int = RECALL_K) -> list:
    """Return the k most relevant memories for `trigger`, marking them recalled."""
    memories = store.all_memories()
    if not memories:
        return []
    now = datetime.now(timezone.utc)
    keywords = _tokens(trigger)
    ranked = sorted(memories, key=lambda m: _score(m, keywords, now), reverse=True)
    chosen = ranked[:k]
    store.bump_recalled([m["id"] for m in chosen])
    return chosen


def build_memory_context(store: Store, trigger: str) -> str:
    """Render active facts and recalled memories into the system-prompt block."""
    facts = store.active_facts()
    memories = top_k(store, trigger)
    if not facts and not memories:
        return ""

    lines: list[str] = []
    if facts:
        lines.append("Facts you know:")
        lines += [f"- [#{f['id']}] {f['text']}" for f in facts]
    if memories:
        if lines:
            lines.append("")
        lines.append("Things you remember:")
        lines += [f"- {m['text']}" for m in sorted(memories, key=lambda m: m["ts"])]
    return "\n".join(lines)
