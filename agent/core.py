"""The agent's turn: build context, call the model, run any tools, persist.

A turn is the classic agentic loop — call the model with the persona prompt,
recalled memory and the conversation window; if it wants a tool, run it and
feed the result back; repeat until it produces a reply. The tools let her
remember things she is told (see agent/tools/remember.py).
"""

import json
import logging
from datetime import datetime, timezone

from openai import AsyncOpenAI

from agent import prompt
from memory.store import TS_FORMAT
from agent.tools.base import ToolRegistry
from agent.tools.media import MediaItem, Outbox, load_stickers, register_media_tools
from agent.tools.remember import register_memory_tools
from agent.tools.remind import register_remind_tool
from agent.tools.schedule import register_schedule_tool
from config import HISTORY_WINDOW, MODEL, OPENAI_API_KEY
from memory.retrieval import build_memory_context
from memory.store import Store

logger = logging.getLogger(__name__)

# gpt-5* are reasoning models: hidden reasoning is billed against this budget
# before any reply or tool call. Reasoning alone can run ~800 tokens, so a tight
# cap starves the visible answer to empty. Leave comfortable headroom.
MAX_TOKENS = 2048
MAX_TOOL_ROUNDS = 8  # safety cap so a tool loop can't spin forever
SILENT = "[silent]"

# A stable key so every turn routes to the same prompt cache. The persona and
# tool schemas lead the request unchanged, so their tokens are served from cache
# (cheaper input) while quality is untouched — the model still sees the full
# prompt. Only the trailing time/memory/history differ per turn.
PROMPT_CACHE_KEY = "ruchi-agent-v1"

PROACTIVE_INSTRUCTION = (
    "This is a self-initiated check-in — the user has not just messaged you. "
    'You earlier planned to reach out for this reason: "{reason}". '
    "Decide whether to message them right now and what to say. If it doesn't "
    f"feel like the right moment, reply with exactly {SILENT} and, if you like, "
    "schedule a later check-in instead."
)


class Agent:
    def __init__(self, store: Store):
        self.store = store
        self.client = AsyncOpenAI(api_key=OPENAI_API_KEY, timeout=60.0)
        self.outbox = Outbox()
        self.tools = ToolRegistry()
        register_memory_tools(self.tools, store)
        register_schedule_tool(self.tools, store)
        register_remind_tool(self.tools, store)
        register_media_tools(self.tools, self.outbox, load_stickers())

    def drain_media(self) -> list[MediaItem]:
        """Take the media she queued this turn, for the I/O layer to deliver."""
        return self.outbox.drain()

    async def reply(self, user_message: str) -> str:
        """React to a message from the user."""
        convo_gap_minutes, last_sender = self._convo_gap()
        self.store.save_message("user", user_message)
        text = await self._run(user_message, convo_gap_minutes=convo_gap_minutes, last_sender=last_sender)
        self.store.save_message("assistant", text)
        logger.info("Replied with %d chars", len(text))
        return text

    def _convo_gap(self) -> tuple[int | None, str | None]:
        """Minutes since the last message + who sent it. Returns (None, None) if no history."""
        last = self.store.last_message()
        if last is None:
            return None, None
        ts, role = last
        last_dt = datetime.strptime(ts, TS_FORMAT).replace(tzinfo=timezone.utc)
        gap = int((datetime.now(timezone.utc) - last_dt).total_seconds() / 60)
        return gap, role

    async def reach_out(self, reason: str) -> str:
        """Run a proactive turn. Returns her message, or "" if she stays silent."""
        instruction = PROACTIVE_INSTRUCTION.format(reason=reason)
        text = await self._run(reason, extra_instruction=instruction)
        if not text.strip() or text.strip() == SILENT:
            return ""
        self.store.save_message("assistant", text)
        logger.info("Reached out with %d chars", len(text))
        return text

    async def _run(
        self,
        trigger: str,
        extra_instruction: str | None = None,
        convo_gap_minutes: int | None = None,
        last_sender: str | None = None,
    ) -> str:
        self.outbox.drain()  # clear any media left by a prior turn
        system = prompt.render(build_memory_context(self.store, trigger), convo_gap_minutes, last_sender)
        messages: list[dict] = [{"role": "system", "content": system}]
        messages += [
            {"role": row["role"], "content": row["content"]}
            for row in self.store.recent_messages(HISTORY_WINDOW)
        ]
        if extra_instruction:
            messages.append({"role": "user", "content": extra_instruction})

        for round_num in range(1, MAX_TOOL_ROUNDS + 1):
            response = await self.client.chat.completions.create(
                model=MODEL,
                max_completion_tokens=MAX_TOKENS,
                tools=self.tools.schemas(),
                messages=messages,
                prompt_cache_key=PROMPT_CACHE_KEY,
            )
            if response.usage:
                details = getattr(response.usage, "prompt_tokens_details", None)
                cached = getattr(details, "cached_tokens", 0) or 0
                logger.info(
                    "Model round %d (%s): %d prompt (%d cached) + %d completion tokens",
                    round_num,
                    MODEL,
                    response.usage.prompt_tokens,
                    cached,
                    response.usage.completion_tokens,
                )
                self.store.log_token_usage(
                    model=MODEL,
                    prompt_tokens=response.usage.prompt_tokens,
                    cached_tokens=cached,
                    completion_tokens=response.usage.completion_tokens,
                    trigger="proactive" if extra_instruction else "reply",
                )
            message = response.choices[0].message
            if not message.tool_calls:
                return message.content or ""

            logger.info(
                "Model requested %d tool call(s): %s",
                len(message.tool_calls),
                ", ".join(c.function.name for c in message.tool_calls),
            )
            messages.append(message.model_dump(exclude_none=True))
            messages += self._run_tools(message.tool_calls)

        logger.warning("Hit tool-round cap (%d); returning without a reply", MAX_TOOL_ROUNDS)
        return ""

    def _run_tools(self, tool_calls) -> list[dict]:
        results = []
        for call in tool_calls:
            try:
                args = json.loads(call.function.arguments or "{}")
            except json.JSONDecodeError:
                args = {}
            output = self.tools.execute(call.function.name, args)
            logger.info("Tool %s -> %s", call.function.name, output)
            results.append(
                {"role": "tool", "tool_call_id": call.id, "content": output}
            )
        return results
