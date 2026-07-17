"""Entrypoint: run the Telegram companion via long polling."""

import asyncio
import logging
import threading

from telegram.ext import Application

from channels.telegram import build_app
from config import DB_PATH, MODEL, OWNER_CHAT_ID
from logging_setup import configure_logging
from memory.store import Store
from scheduler import run_reflection_loop

logger = logging.getLogger(__name__)

DASHBOARD_PORT = 5050


def _start_dashboard() -> None:
    """Run the Flask dashboard in a background daemon thread."""
    try:
        from dashboard import app as dash_app
        dash_app.run(host="0.0.0.0", port=DASHBOARD_PORT, debug=False, use_reloader=False)
    except Exception:
        logger.exception("Dashboard failed to start")


def main() -> None:
    configure_logging()
    store = Store(DB_PATH)
    lock = asyncio.Lock()

    t = threading.Thread(target=_start_dashboard, daemon=True, name="dashboard")
    t.start()
    logger.info("Dashboard → http://localhost:%d", DASHBOARD_PORT)

    async def start_reflection(app: Application) -> None:
        app.create_task(run_reflection_loop(store, lock))
        logger.info("Nightly reflection started (proactive messaging disabled)")

    app = build_app(store, lock, post_init=start_reflection)
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
