"""One-time helper: capture Telegram sticker file_ids into media/stickers.json.

Telegram can only resend a sticker by its file_id, and file_ids aren't
guessable — you collect them once from a real pack. Run this, then in the chat:
send a plain message naming a mood ("love", "laugh", "sulk"), then send the
stickers that fit it. Each sticker is filed under the current mood and saved
immediately. Switch mood by sending another mood word. Stop with Ctrl+C —
media/stickers.json is then ready for send_sticker.

    python dev/collect_stickers.py
"""

import json
import logging
import urllib.error
import urllib.request
from pathlib import Path

from telegram import Update
from telegram.ext import Application, ContextTypes, MessageHandler, filters

from config import OWNER_CHAT_ID, TELEGRAM_TOKEN

logger = logging.getLogger(__name__)

STICKERS_PATH = Path("media/stickers.json")


def preflight(token: str) -> None:
    """Fail fast if another process is already polling this bot token.

    Telegram allows only one getUpdates consumer per token, so running this
    collector while the main bot is up produces an endless 409 Conflict loop
    inside run_polling(). A single getUpdates here surfaces that as a clear
    error instead. It uses no offset, so it confirms nothing — any pending
    updates stay queued for whichever poller runs next.
    """
    url = f"https://api.telegram.org/bot{token}/getUpdates?timeout=0"
    try:
        urllib.request.urlopen(url, timeout=10)
    except urllib.error.HTTPError as exc:
        if exc.code == 409:
            raise SystemExit(
                "Another process is already polling this bot token — most "
                "likely your main bot. Stop it first, then rerun this "
                "collector. Telegram allows only one poller per token, so the "
                "two can't share it."
            )
        raise


def load() -> dict[str, list[str]]:
    if STICKERS_PATH.exists():
        return json.loads(STICKERS_PATH.read_text(encoding="utf-8"))
    return {}


def save(stickers: dict[str, list[str]]) -> None:
    STICKERS_PATH.parent.mkdir(parents=True, exist_ok=True)
    STICKERS_PATH.write_text(
        json.dumps(stickers, indent=2, ensure_ascii=False), encoding="utf-8"
    )


async def on_mood(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if update.message.chat_id != OWNER_CHAT_ID:
        return
    mood = update.message.text.strip().lower().removeprefix("mood:").strip()
    context.bot_data["mood"] = mood
    await update.message.reply_text(f"Filing stickers under '{mood}'. Send some.")


async def on_sticker(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if update.message.chat_id != OWNER_CHAT_ID:
        return
    mood = context.bot_data.get("mood")
    if not mood:
        await update.message.reply_text("First send a mood word, e.g. 'love'.")
        return

    stickers = load()
    file_ids = stickers.setdefault(mood, [])
    file_id = update.message.sticker.file_id
    if file_id in file_ids:
        await update.message.reply_text(f"Already saved under '{mood}'.")
        return

    file_ids.append(file_id)
    save(stickers)
    await update.message.reply_text(f"Saved to '{mood}' ({len(file_ids)} total).")


def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")
    preflight(TELEGRAM_TOKEN)
    app = Application.builder().token(TELEGRAM_TOKEN).build()
    app.add_handler(MessageHandler(filters.Sticker.ALL, on_sticker))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, on_mood))
    logger.info("Send a mood word, then stickers. Ctrl+C to stop.")
    app.run_polling()


if __name__ == "__main__":
    main()
