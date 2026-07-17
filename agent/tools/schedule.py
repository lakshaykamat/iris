"""Self-scheduling: the tool she uses to plan when to reach out next.

Calling this writes a pending row to the schedule; the heartbeat in
scheduler.py wakes at that time and gives her the chance to message first.
This is the mechanism behind the whole promise — she reaches out later
because, right now, she decided to.
"""

from datetime import datetime, timedelta, timezone

from agent.tools.base import Tool, ToolRegistry
from memory.store import TS_FORMAT, Store

MIN_HOURS = 0.25
MAX_HOURS = 24 * 14


def _schedule_next_checkin(store: Store, tool_input: dict) -> str:
    hours = max(MIN_HOURS, min(MAX_HOURS, float(tool_input["hours_from_now"])))
    reason = tool_input["reason"].strip()
    fire_at = (datetime.now(timezone.utc) + timedelta(hours=hours)).strftime(TS_FORMAT)
    store.add_checkin(fire_at, reason)
    return f"Planned a check-in in {hours:g}h: {reason}"


def register_schedule_tool(registry: ToolRegistry, store: Store) -> None:
    registry.register(
        Tool(
            name="schedule_next_checkin",
            description=(
                "Plan to message the user again on your own later — for example to "
                "follow up on something they mentioned. Give the delay in hours from "
                "now and a short reason you'll want to remember when the time comes."
            ),
            input_schema={
                "type": "object",
                "properties": {
                    "hours_from_now": {
                        "type": "number",
                        "description": "How many hours from now to reach out.",
                    },
                    "reason": {
                        "type": "string",
                        "description": "Why you're reaching out then (e.g. 'ask how the interview went').",
                    },
                },
                "required": ["hours_from_now", "reason"],
            },
            handler=lambda i: _schedule_next_checkin(store, i),
        )
    )
