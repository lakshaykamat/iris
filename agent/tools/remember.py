"""Memory tools: let the agent decide what is worth keeping.

`remember_fact` stores durable truths (and can correct an earlier one);
`remember_event` stores episodic moments with an importance the agent chooses.
Together these are what make recall possible days later.
"""

from agent.tools.base import Tool, ToolRegistry
from memory.store import Store

MIN_IMPORTANCE = 1
MAX_IMPORTANCE = 10


def _remember_fact(store: Store, tool_input: dict) -> str:
    text = tool_input["text"].strip()
    supersedes = tool_input.get("supersedes")
    if supersedes is not None:
        store.supersede_fact(int(supersedes), text, source="agent")
        return f"Updated fact #{supersedes}: {text}"
    fact_id = store.save_fact(text, source="agent")
    return f"Saved fact #{fact_id}: {text}"


def _remember_event(store: Store, tool_input: dict) -> str:
    text = tool_input["text"].strip()
    importance = max(MIN_IMPORTANCE, min(MAX_IMPORTANCE, int(tool_input["importance"])))
    store.save_memory(text, kind="event", importance=importance)
    return f"Remembered (importance {importance}): {text}"


def register_memory_tools(registry: ToolRegistry, store: Store) -> None:
    registry.register(
        Tool(
            name="remember_fact",
            description=(
                "Save a durable fact about the user, yourself, or the relationship "
                "(names, preferences, ongoing situations). To correct or update an "
                "existing fact, pass its id as `supersedes`."
            ),
            input_schema={
                "type": "object",
                "properties": {
                    "text": {"type": "string", "description": "The fact to remember."},
                    "supersedes": {
                        "type": "integer",
                        "description": "Id of an existing fact this replaces, if any.",
                    },
                },
                "required": ["text"],
            },
            handler=lambda i: _remember_fact(store, i),
        )
    )
    registry.register(
        Tool(
            name="remember_event",
            description=(
                "Record something that happened as an episodic memory, with an "
                "importance from 1 (trivial) to 10 (life-changing). Use it for "
                "moments worth recalling later — news the user shared, how they felt."
            ),
            input_schema={
                "type": "object",
                "properties": {
                    "text": {"type": "string", "description": "What happened."},
                    "importance": {
                        "type": "integer",
                        "description": "1 (trivial) to 10 (major).",
                    },
                },
                "required": ["text", "importance"],
            },
            handler=lambda i: _remember_event(store, i),
        )
    )
