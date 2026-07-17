"""Central configuration, loaded from the environment (.env in development)."""

import os
from pathlib import Path

from dotenv import load_dotenv

load_dotenv()


def _require(name: str) -> str:
    value = os.getenv(name)
    if not value:
        raise RuntimeError(f"Missing required environment variable: {name}")
    return value


# Required — the bot cannot start without these.
TELEGRAM_TOKEN = _require("TELEGRAM_TOKEN")
OWNER_CHAT_ID = int(_require("OWNER_CHAT_ID"))

# Optional — sensible defaults match .env.example.
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY", "")
OWNER_TZ = os.getenv("OWNER_TZ", "Asia/Kolkata")
MODEL = os.getenv("MODEL", "gpt-5-mini")
GATE_MODEL = os.getenv("GATE_MODEL", "gpt-5-nano")
MAX_SILENCE_HOURS = int(os.getenv("MAX_SILENCE_HOURS", "24"))
HISTORY_WINDOW = int(os.getenv("HISTORY_WINDOW", "30"))
DEBOUNCE_SECONDS = int(os.getenv("DEBOUNCE_SECONDS", "3"))
PRESENCE_WINDOW_MIN = int(os.getenv("PRESENCE_WINDOW_MIN", "5"))
REFLECTION_HOUR = int(os.getenv("REFLECTION_HOUR", "3"))
GIF_PROVIDER = os.getenv("GIF_PROVIDER", "tenor")
GIF_API_KEY = os.getenv("GIF_API_KEY", "")

DB_PATH = Path("data/agent.db")
