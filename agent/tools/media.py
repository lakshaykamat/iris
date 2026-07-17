"""Expressive media: the stickers and GIFs she drops into a reply.

She doesn't type these — mid-turn she calls `send_sticker(mood)` or
`send_gif(query)` and the item is queued on the turn's `Outbox`. The I/O layer
delivers the queue after her text bubbles, so a turn can read as
"omg" → [sticker] → "i'm so happy for you". Stickers map a mood to a
pre-collected Telegram file_id (media/stickers.json, filled by
tools/collect_stickers.py); GIFs are searched on Tenor or Giphy at send time.
Restraint is a persona rule, not enforced here — see persona.md.
"""

import json
import logging
import random
from dataclasses import dataclass, field
from pathlib import Path

import httpx

from agent.tools.base import Tool, ToolRegistry
from config import GIF_API_KEY, GIF_PROVIDER

logger = logging.getLogger(__name__)

STICKERS_PATH = Path("media/stickers.json")
GIF_TIMEOUT_SECONDS = 8.0


@dataclass
class MediaItem:
    """One queued send. `payload` is a sticker file_id or a GIF search query;
    `note` is the short line saved to message history so she recalls it."""

    kind: str  # "sticker" | "gif"
    payload: str
    note: str


@dataclass
class Outbox:
    """Media queued during a turn, delivered by the I/O layer afterwards."""

    items: list[MediaItem] = field(default_factory=list)

    def add(self, item: MediaItem) -> None:
        self.items.append(item)

    def drain(self) -> list[MediaItem]:
        """Return the queued items and reset for the next turn."""
        items = self.items
        self.items = []
        return items


def load_stickers() -> dict[str, list[str]]:
    """Load the mood → file_ids library, or {} if none has been collected yet."""
    if not STICKERS_PATH.exists():
        return {}
    return json.loads(STICKERS_PATH.read_text(encoding="utf-8"))


async def search_gif(query: str) -> str | None:
    """Return the best matching GIF url from the configured provider, or None."""
    if not GIF_API_KEY:
        return None
    try:
        async with httpx.AsyncClient(timeout=GIF_TIMEOUT_SECONDS) as client:
            if GIF_PROVIDER == "giphy":
                return await _search_giphy(client, query)
            return await _search_tenor(client, query)
    except (httpx.HTTPError, KeyError, IndexError) as error:
        logger.warning("GIF search failed for %r: %s", query, error)
        return None


async def _search_tenor(client: httpx.AsyncClient, query: str) -> str | None:
    response = await client.get(
        "https://tenor.googleapis.com/v2/search",
        params={"q": query, "key": GIF_API_KEY, "limit": 1, "media_filter": "gif"},
    )
    response.raise_for_status()
    results = response.json()["results"]
    return results[0]["media_formats"]["gif"]["url"] if results else None


async def _search_giphy(client: httpx.AsyncClient, query: str) -> str | None:
    response = await client.get(
        "https://api.giphy.com/v1/gifs/search",
        params={"q": query, "api_key": GIF_API_KEY, "limit": 1},
    )
    response.raise_for_status()
    data = response.json()["data"]
    return data[0]["images"]["original"]["url"] if data else None


def _send_sticker(outbox: Outbox, stickers: dict[str, list[str]], tool_input: dict) -> str:
    mood = tool_input["mood"].strip().lower()
    file_ids = stickers.get(mood)
    if not file_ids:
        available = ", ".join(sorted(stickers))
        return f"No sticker for mood '{mood}'. Available moods: {available}."
    outbox.add(MediaItem("sticker", random.choice(file_ids), note=f"[sticker: {mood}]"))
    return f"Queued a {mood} sticker."


def _send_gif(outbox: Outbox, tool_input: dict) -> str:
    query = tool_input["query"].strip()
    outbox.add(MediaItem("gif", query, note=f"[gif: {query}]"))
    return f"Queued a gif for: {query}"


def register_media_tools(
    registry: ToolRegistry, outbox: Outbox, stickers: dict[str, list[str]]
) -> None:
    """Register the media tools she can actually use.

    A tool is only offered when it can work: `send_sticker` needs a collected
    library, `send_gif` needs a provider key. With neither, she stays text-only.
    """
    if stickers:
        registry.register(
            Tool(
                name="send_sticker",
                description=(
                    "Send a sticker that fits the moment. Use sparingly, only when "
                    "you're genuinely warm or excited — never on every message. "
                    "Pick the mood that matches how you feel."
                ),
                input_schema={
                    "type": "object",
                    "properties": {
                        "mood": {
                            "type": "string",
                            "enum": sorted(stickers),
                            "description": "The mood the sticker should express.",
                        },
                    },
                    "required": ["mood"],
                },
                handler=lambda i: _send_sticker(outbox, stickers, i),
            )
        )
    if GIF_API_KEY:
        registry.register(
            Tool(
                name="send_gif",
                description=(
                    "Send a GIF when it says something better than words can — a "
                    "reaction, a celebration. Use it rarely, when the feeling is "
                    "strong. Describe what to search for, e.g. 'excited happy dance'."
                ),
                input_schema={
                    "type": "object",
                    "properties": {
                        "query": {
                            "type": "string",
                            "description": "What to search for on the GIF provider.",
                        },
                    },
                    "required": ["query"],
                },
                handler=lambda i: _send_gif(outbox, i),
            )
        )
