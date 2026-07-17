"""Telegram I/O — inbound debounced messages, in-character replies delivered
the way a person texts: a typing indicator, short bubbles, small pauses.
"""

import asyncio
import logging
import time

from telegram import Update
from telegram.constants import ChatAction
from telegram.error import Conflict, NetworkError, TelegramError
from telegram.ext import Application, ContextTypes, MessageHandler, filters

from agent.core import Agent
from agent.tools.media import MediaItem, search_gif
from config import DEBOUNCE_SECONDS, OWNER_CHAT_ID, TELEGRAM_TOKEN
from memory.store import Store
from scheduler import run_heartbeat, run_reflection_loop

logger = logging.getLogger(__name__)

MAX_TYPING_SECONDS = 4.0
CHARS_PER_SECOND = 40


class Debouncer:
    """Collapses messages sent in quick succession into a single turn."""

    def __init__(self, delay_seconds: float, on_flush):
        self.delay = delay_seconds
        self.on_flush = on_flush
        self.buffer: list[str] = []
        self.chat_id: int | None = None
        self.pending: asyncio.Task | None = None

    def add(self, chat_id: int, text: str) -> None:
        self.chat_id = chat_id
        self.buffer.append(text)
        if self.pending:
            self.pending.cancel()
        self.pending = asyncio.create_task(self._flush_after_delay())

    async def _flush_after_delay(self) -> None:
        try:
            await asyncio.sleep(self.delay)
        except asyncio.CancelledError:
            return
        text = "\n".join(self.buffer)
        chat_id = self.chat_id
        self.buffer = []
        self.pending = None
        await self.on_flush(chat_id, text)


def split_bubbles(text: str) -> list[str]:
    return [line.strip() for line in text.splitlines() if line.strip()]


def typing_seconds(text: str) -> float:
    return min(len(text) / CHARS_PER_SECOND, MAX_TYPING_SECONDS)


async def send_human(bot, chat_id: int, text: str) -> None:
    for bubble in split_bubbles(text):
        await bot.send_chat_action(chat_id, ChatAction.TYPING)
        await asyncio.sleep(typing_seconds(bubble))
        await bot.send_message(chat_id, bubble)


async def deliver_media(bot, chat_id: int, items: list[MediaItem], store: Store) -> None:
    """Send the stickers and GIFs she queued this turn, and remember each one."""
    for item in items:
        if item.kind == "sticker":
            await bot.send_sticker(chat_id, item.payload)
        else:
            url = await search_gif(item.payload)
            if url is None:
                logger.info("No GIF found for %r; skipping", item.payload)
                continue
            await bot.send_animation(chat_id, url)
        store.save_message("assistant", item.note, kind=item.kind)


async def on_message(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    message = update.message
    if message is None or message.text is None:
        return
    if message.chat_id != OWNER_CHAT_ID:
        logger.warning(
            "Ignoring message from unauthorized chat %s (from user %s)",
            message.chat_id,
            message.from_user.id if message.from_user else "?",
        )
        return

    logger.info("Inbound message (%d chars), debouncing", len(message.text))
    context.bot_data["debouncer"].add(message.chat_id, message.text)


async def on_error(update: object, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Central error handler so failures are one clear line, not a raw traceback.

    Without this, python-telegram-bot logs "No error handlers are registered"
    and dumps a full stack for routine, self-healing errors — most notably the
    409 Conflict you hit when a second bot instance polls the same token.
    """
    error = context.error
    if isinstance(error, Conflict):
        logger.error(
            "Telegram 409 Conflict: another instance is polling this bot token. "
            "Make sure only one bot process runs (check for a second terminal, a "
            "leftover process, or a deployed copy). Retrying..."
        )
    elif isinstance(error, NetworkError):
        logger.warning("Telegram network error (will retry): %s", error)
    elif isinstance(error, TelegramError):
        logger.error("Telegram API error: %s", error)
    else:
        logger.exception("Unexpected error while handling update", exc_info=error)


def build_app(store: Store) -> Application:
    app = Application.builder().token(TELEGRAM_TOKEN).post_init(_start_autonomy).build()
    agent = Agent(store)
    lock = asyncio.Lock()

    async def handle_turn(chat_id: int, text: str) -> None:
        logger.info("Turn start: %d chars of debounced input", len(text))
        started = time.monotonic()
        try:
            async with lock:
                reply = await agent.reply(text)
                media = agent.drain_media()
            await send_human(app.bot, chat_id, reply)
            await deliver_media(app.bot, chat_id, media, store)
            logger.info(
                "Turn done in %.1fs: %d bubbles, %d media item(s)",
                time.monotonic() - started,
                len(split_bubbles(reply)),
                len(media),
            )
        except Exception:
            logger.exception("Turn failed for chat %d; dropping", chat_id)

    app.bot_data["store"] = store
    app.bot_data["agent"] = agent
    app.bot_data["lock"] = lock
    app.bot_data["debouncer"] = Debouncer(DEBOUNCE_SECONDS, handle_turn)
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, on_message))
    app.add_error_handler(on_error)
    return app


async def _start_autonomy(app: Application) -> None:
    """Launch the heartbeat and reflection loops alongside Telegram polling.

    They share the same lock as the message handler so a proactive turn and a
    reply can never run at once and corrupt the conversation.
    """
    store = app.bot_data["store"]
    agent = app.bot_data["agent"]
    lock = app.bot_data["lock"]

    async def send(text: str, media: list[MediaItem]) -> None:
        await send_human(app.bot, OWNER_CHAT_ID, text)
        await deliver_media(app.bot, OWNER_CHAT_ID, media, store)

    app.create_task(run_heartbeat(store, agent, lock, send))
    app.create_task(run_reflection_loop(store, lock))
    logger.info("Autonomy started: heartbeat + nightly reflection")
