"""Reflection: distill recent events into higher-level insights.

Periodically she re-reads what has happened lately and writes back a few
`reflection` memories — the mechanism that lets her notice patterns ("he's been
stressed this week") instead of treating every event in isolation. The
scheduling that triggers this lands in Phase 6; here we own the distillation.
"""

import json
import logging

from openai import AsyncOpenAI

from config import MODEL, OPENAI_API_KEY
from memory.store import Store

logger = logging.getLogger(__name__)

MIN_EVENTS = 5
MAX_INSIGHTS = 3
REFLECTION_IMPORTANCE = 7
MAX_TOKENS = 512

INSTRUCTION = (
    "You are reviewing recent memories from a personal companion's life with the "
    "person she cares about. Distil at most three short, higher-level insights about "
    "how they are doing or patterns you notice — not a restatement of each event. "
    "Respond ONLY with a JSON array of strings."
)


def _parse_insights(text: str) -> list[str]:
    text = text.strip()
    try:
        data = json.loads(text)
        if isinstance(data, list):
            return [str(item).strip() for item in data if str(item).strip()]
    except json.JSONDecodeError:
        pass
    return [line.strip("-* ").strip() for line in text.splitlines() if line.strip()]


async def run_reflection(store: Store, client: AsyncOpenAI | None = None) -> list[str]:
    """Summarise events since the last reflection into new reflection memories."""
    client = client or AsyncOpenAI(api_key=OPENAI_API_KEY)
    events = store.events_since(store.last_reflection_ts())
    if len(events) < MIN_EVENTS:
        logger.info("Reflection skipped: only %d new events", len(events))
        return []

    recent = "\n".join(f"- {event['text']}" for event in events)
    response = await client.chat.completions.create(
        model=MODEL,
        max_completion_tokens=MAX_TOKENS,
        messages=[
            {"role": "system", "content": INSTRUCTION},
            {"role": "user", "content": recent},
        ],
    )
    text = response.choices[0].message.content or ""

    insights = _parse_insights(text)[:MAX_INSIGHTS]
    for insight in insights:
        store.save_memory(insight, kind="reflection", importance=REFLECTION_IMPORTANCE)
    logger.info("Reflection wrote %d insights from %d events", len(insights), len(events))
    return insights
