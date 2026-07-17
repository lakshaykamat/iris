"""Autonomy: the heartbeat that lets her text first, plus nightly reflection.

The heartbeat sleeps until her next planned check-in, then decides whether to
reach out — skipping if you were just talking, asking a cheap gate model if the
moment fits, and always leaving a future check-in behind so she never goes
silent forever. Every decision is logged so the autonomy stays debuggable.

Run `python scheduler.py "<reason>"` to fire one proactive turn on demand
without waiting for a real check-in (prints instead of sending).
"""

import asyncio
import logging
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo

from openai import AsyncOpenAI

from agent.core import Agent
from config import (
    DB_PATH,
    GATE_MODEL,
    MAX_SILENCE_HOURS,
    OPENAI_API_KEY,
    OWNER_TZ,
    PRESENCE_WINDOW_MIN,
    REFLECTION_HOUR,
)
from memory.reflection import run_reflection
from memory.store import TS_FORMAT, Store

logger = logging.getLogger(__name__)

SEED_CHECKIN_HOURS = 6
PRESENCE_DEFER_MINUTES = 30
REFLECT_AFTER_EVENTS = 12
GATE_MAX_TOKENS = 200


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _parse(ts: str) -> datetime:
    return datetime.strptime(ts, TS_FORMAT).replace(tzinfo=timezone.utc)


def _format(when: datetime) -> str:
    return when.strftime(TS_FORMAT)


def _seconds_until(fire_at: str) -> float:
    """Seconds until a check-in, capped so she never sleeps past the safety floor."""
    delta = (_parse(fire_at) - _now()).total_seconds()
    return max(0.0, min(delta, MAX_SILENCE_HOURS * 3600))


def _user_active(store: Store) -> bool:
    ts = store.last_user_message_ts()
    return ts is not None and _parse(ts) > _now() - timedelta(minutes=PRESENCE_WINDOW_MIN)


def ensure_upcoming_checkin(store: Store) -> None:
    """Guarantee a pending check-in within the safety floor.

    Covers cold start (none scheduled yet), the reschedule invariant (never end
    a heartbeat with nothing planned), and the floor itself (never quieter than
    MAX_SILENCE_HOURS).
    """
    nxt = store.next_pending_checkin()
    if nxt is None:
        fire_at = _format(_now() + timedelta(hours=SEED_CHECKIN_HOURS))
        store.add_checkin(fire_at, "it's been quiet — see how they're doing")
    elif _parse(nxt["fire_at"]) > _now() + timedelta(hours=MAX_SILENCE_HOURS):
        fire_at = _format(_now() + timedelta(hours=MAX_SILENCE_HOURS))
        store.add_checkin(fire_at, "just checking in — it's been a while")


class ReachOutGate:
    """A cheap model that answers one question: is now a good moment to text?"""

    def __init__(self, client: AsyncOpenAI | None = None):
        self.client = client or AsyncOpenAI(api_key=OPENAI_API_KEY, timeout=60.0)

    async def should_reach_out(self, store: Store, reason: str) -> bool:
        recent = store.recent_messages(6)
        transcript = "\n".join(f"{m['role']}: {m['content']}" for m in recent)
        prompt = (
            f"You are a gate deciding whether to send a proactive message.\n"
            f"Planned reason: {reason}\n\n"
            f"Recent conversation:\n{transcript or '(no messages yet)'}\n\n"
            "Send the message UNLESS one of these is true:\n"
            "1. The user explicitly asked to not be disturbed or left alone.\n"
            "2. A message on this exact topic was already sent in the last hour.\n"
            "3. The conversation is actively ongoing right now.\n"
            "Default to YES. Answer only yes or no."
        )
        response = await self.client.chat.completions.create(
            model=GATE_MODEL,
            max_completion_tokens=GATE_MAX_TOKENS,
            messages=[{"role": "user", "content": prompt}],
        )
        answer = (response.choices[0].message.content or "").strip().lower()
        return answer.startswith("y")


async def handle_checkin(store: Store, agent: Agent, gate: ReachOutGate, send, checkin) -> None:
    """Run one due check-in end to end: presence, gate, send-or-stay-silent, log."""
    reason = checkin["reason"]
    pinned = bool(checkin["pinned"])

    if not pinned and _user_active(store):
        deferred_to = _format(_now() + timedelta(minutes=PRESENCE_DEFER_MINUTES))
        store.reschedule_checkin(checkin["id"], deferred_to)
        store.log_decision("deferred", f"user active; {reason}")
        logger.info("Check-in deferred, user just talked: %s", reason)
        return

    if not pinned and not await gate.should_reach_out(store, reason):
        declines = store.increment_gate_declines(checkin["id"])
        if declines >= 3:
            store.mark_checkin_done(checkin["id"])
            store.log_decision("silent", f"gate declined {declines}x, giving up; {reason}")
            logger.info("Check-in skipped by gate (final): %s", reason)
        else:
            retry_at = _format(_now() + timedelta(hours=2))
            store.reschedule_checkin(checkin["id"], retry_at)
            store.log_decision("gate_retry", f"gate declined ({declines}/3), retry in 2h; {reason}")
            logger.info("Check-in gate declined (%d/3), rescheduled 2h: %s", declines, reason)
        return

    text = await agent.reach_out(reason)
    media = agent.drain_media()
    store.mark_checkin_done(checkin["id"])
    if text:
        await send(text, media)
        store.log_decision("sent", reason)
        logger.info("%s: %s", "Reminder sent" if pinned else "Reached out", reason)
    else:
        store.log_decision("silent", f"chose not to; {reason}")
        logger.info("Chose silence: %s", reason)


async def _maybe_reflect(store: Store) -> None:
    """Reflect once enough new events have piled up, between the nightly runs."""
    if len(store.events_since(store.last_reflection_ts())) >= REFLECT_AFTER_EVENTS:
        await run_reflection(store)


HEARTBEAT_POLL_SECONDS = 60.0


async def run_heartbeat(store: Store, agent: Agent, lock: asyncio.Lock, send) -> None:
    """Sleep until each planned check-in, then let her decide whether to text.

    Polls at most every HEARTBEAT_POLL_SECONDS so newly added reminders are
    picked up promptly instead of waiting for a sleep started hours earlier.
    """
    gate = ReachOutGate()
    ensure_upcoming_checkin(store)
    while True:
        nxt = store.next_pending_checkin()
        secs = _seconds_until(nxt["fire_at"]) if nxt else HEARTBEAT_POLL_SECONDS
        await asyncio.sleep(min(secs, HEARTBEAT_POLL_SECONDS))

        nxt = store.next_pending_checkin()
        if nxt is None or _seconds_until(nxt["fire_at"]) > 0:
            continue

        async with lock:
            try:
                await handle_checkin(store, agent, gate, send, nxt)
                await _maybe_reflect(store)
            except Exception:
                logger.exception("Heartbeat turn failed; loop continues")
        ensure_upcoming_checkin(store)


def _seconds_until_hour(hour: int) -> float:
    now = datetime.now(ZoneInfo(OWNER_TZ))
    target = now.replace(hour=hour, minute=0, second=0, microsecond=0)
    if target <= now:
        target += timedelta(days=1)
    return (target - now).total_seconds()


async def run_reflection_loop(store: Store, lock: asyncio.Lock) -> None:
    """Consolidate recent memories into insights, nightly at REFLECTION_HOUR."""
    while True:
        await asyncio.sleep(_seconds_until_hour(REFLECTION_HOUR))
        async with lock:
            try:
                await run_reflection(store)
            except Exception:
                logger.exception("Nightly reflection failed; will retry tomorrow")


async def _simulate(reason: str | None) -> None:
    store = Store(DB_PATH)
    agent = Agent(store)
    ensure_upcoming_checkin(store)
    checkin = store.next_pending_checkin()
    if reason and checkin is not None:
        checkin = {"id": checkin["id"], "reason": reason, "pinned": checkin["pinned"]}

    async def send(text: str, media) -> None:
        extras = "".join(f"\n{item.note}" for item in media)
        print(f"\n--- she would send ---\n{text}{extras}\n----------------------\n")

    await handle_checkin(store, agent, ReachOutGate(), send, checkin)


if __name__ == "__main__":
    import sys

    from logging_setup import configure_logging

    configure_logging()
    asyncio.run(_simulate(" ".join(sys.argv[1:]) or None))
