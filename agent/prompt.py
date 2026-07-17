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


def build_system_prompt(persona: str, now: datetime, memory_context: str = "") -> str:
    """Assemble the full system prompt from the persona sheet and live context.

    `memory_context` is a pre-rendered block of recalled facts and memories
    (see memory/retrieval.py); the persona still renders fully without it.
    """
    parts = [
        persona,
        "",
        "# Right now",
        f"It is {now:%A, %d %B %Y, %I:%M %p} in {OWNER_TZ}.",
    ]
    if memory_context.strip():
        parts += ["", "# What you remember", memory_context.strip()]
    return "\n".join(parts)


def render(memory_context: str = "") -> str:
    """Render the current system prompt as it would be sent to the model."""
    now = datetime.now(ZoneInfo(OWNER_TZ))
    return build_system_prompt(load_persona(), now, memory_context)


if __name__ == "__main__":
    print(render())
