"""One place to configure logging so every entrypoint reads the same.

Keeps our own logs at INFO while muting the libraries that would otherwise
drown them — httpx logs a line for every Telegram/OpenAI HTTP call, and
telegram.ext is chatty at INFO. Call `configure_logging()` once at startup.
"""

import logging
import os

FORMAT = "%(asctime)s %(levelname)-7s %(name)s: %(message)s"
DATE_FORMAT = "%H:%M:%S"

# Libraries that are noisy at INFO but useful at WARNING.
_NOISY = {
    "httpx": logging.WARNING,
    "httpcore": logging.WARNING,
    "telegram.ext.Application": logging.WARNING,
    "apscheduler": logging.WARNING,
}


def configure_logging() -> None:
    """Set up root logging from the LOG_LEVEL env var (default INFO)."""
    level = getattr(logging, os.getenv("LOG_LEVEL", "INFO").upper(), logging.INFO)
    logging.basicConfig(level=level, format=FORMAT, datefmt=DATE_FORMAT)
    for name, noisy_level in _NOISY.items():
        logging.getLogger(name).setLevel(noisy_level)
