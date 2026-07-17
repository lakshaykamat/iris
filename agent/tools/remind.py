"""User-requested reminders: always delivered, gate and presence checks bypassed."""

from datetime import datetime, timedelta, timezone

from agent.tools.base import Tool, ToolRegistry
from memory.store import TS_FORMAT, Store

MIN_HOURS = 1 / 60  # 1 minute floor
MAX_HOURS = 24 * 14


def _set_reminder(store: Store, tool_input: dict) -> str:
    hours = max(MIN_HOURS, min(MAX_HOURS, float(tool_input["hours_from_now"])))
    reason = tool_input["reason"].strip()
    fire_at = (datetime.now(timezone.utc) + timedelta(hours=hours)).strftime(TS_FORMAT)
    store.add_reminder(fire_at, reason)
    return f"Reminder set for {hours:g}h from now: {reason}"


def register_remind_tool(registry: ToolRegistry, store: Store) -> None:
    registry.register(
        Tool(
            name="set_reminder",
            description=(
                "Set a guaranteed reminder for the user — use this when he explicitly "
                "asks to be reminded of something at a specific time. Unlike a check-in, "
                "this always fires and is never silenced by the gate."
            ),
            input_schema={
                "type": "object",
                "properties": {
                    "hours_from_now": {
                        "type": "number",
                        "description": "How many hours from now to send the reminder.",
                    },
                    "reason": {
                        "type": "string",
                        "description": "What to remind him about (e.g. 'eat something').",
                    },
                },
                "required": ["hours_from_now", "reason"],
            },
            handler=lambda i: _set_reminder(store, i),
        )
    )
