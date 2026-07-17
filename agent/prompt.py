"""Builds the system prompt: the persona sheet plus live context.

The persona sheet is static character; the context block is what changes each
turn (the current time, and later the recalled memories). Keeping them separate
lets the persona half stay cacheable while the context half is rebuilt per turn.
"""

from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

from config import OWNER_TZ

PERSONA_PATH = Path("persona.md")


def load_persona() -> str:
    return PERSONA_PATH.read_text(encoding="utf-8").strip()


def _gap_str(minutes: int) -> str:
    if minutes < 60:
        return f"{minutes} minutes"
    if minutes < 120:
        return "about an hour"
    if minutes < 1440:
        return f"about {minutes // 60} hours"
    days = minutes // 1440
    return f"about {days} day{'s' if days > 1 else ''}"


def build_system_prompt(
    persona: str,
    now: datetime,
    memory_context: str = "",
    convo_gap_minutes: int | None = None,
    last_sender: str | None = None,
) -> str:
    """Assemble the full system prompt from the persona sheet and live context.

    `convo_gap_minutes` + `last_sender` describe the silence since the last
    message. When the gap is ≥30 min the prompt gains a conversation-gap note
    so Ruchi can react the way a real person would to a long silence.
    """
    parts = [
        persona,
        "",
        "# Right now",
        f"It is {now:%A, %d %B %Y, %I:%M %p} in {OWNER_TZ}.",
    ]
    if convo_gap_minutes is not None and convo_gap_minutes >= 30:
        gap = _gap_str(convo_gap_minutes)
        if last_sender == "assistant":
            note = f"You texted him {gap} ago — he's only just replying now."
        else:
            note = f"He last texted {gap} ago and is texting you again now."
        parts += [
            "",
            "# Conversation gap",
            note,
            "React the way you naturally would to this silence. Don't announce it, just let it colour your tone.",
        ]
    if memory_context.strip():
        parts += ["", "# What you remember", memory_context.strip()]
    return "\n".join(parts)


def render(
    memory_context: str = "",
    convo_gap_minutes: int | None = None,
    last_sender: str | None = None,
) -> str:
    """Render the current system prompt as it would be sent to the model."""
    now = datetime.now(ZoneInfo(OWNER_TZ))
    return build_system_prompt(load_persona(), now, memory_context, convo_gap_minutes, last_sender)


if __name__ == "__main__":
    print(render())
