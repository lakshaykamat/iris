"""Entrypoint: run the Telegram companion via long polling."""

import logging

from channels.telegram import build_app
from config import DB_PATH, MODEL, OWNER_CHAT_ID
from logging_setup import configure_logging
from memory.store import Store

logger = logging.getLogger(__name__)


def main() -> None:
    configure_logging()
    store = Store(DB_PATH)
    app = build_app(store)
    logger.info(
        "iris starting (model=%s, owner_chat=%s, db=%s)",
        MODEL,
        OWNER_CHAT_ID,
        DB_PATH,
    )
    # drop_pending_updates avoids replaying the backlog a second instance may
    # have left behind, and keeps a clean handoff after a restart.
    app.run_polling(drop_pending_updates=True)
    logger.info("iris stopped")


if __name__ == "__main__":
    main()
