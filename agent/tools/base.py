"""The tool bus: a minimal registry pairing a tool's schema with its handler.

A `Tool` couples the schema the model sees with the Python function that runs
when the model calls it. The registry emits every schema for the API request
and dispatches each tool call to the matching handler. New tools drop in
by registering here — the agent loop never changes.
"""

from collections.abc import Callable
from dataclasses import dataclass

Handler = Callable[[dict], str]


@dataclass(frozen=True)
class Tool:
    name: str
    description: str
    input_schema: dict
    handler: Handler

    def schema(self) -> dict:
        """The tool definition as the OpenAI Chat Completions API expects it."""
        return {
            "type": "function",
            "function": {
                "name": self.name,
                "description": self.description,
                "parameters": self.input_schema,
            },
        }


class ToolRegistry:
    def __init__(self) -> None:
        self._tools: dict[str, Tool] = {}

    def register(self, tool: Tool) -> None:
        self._tools[tool.name] = tool

    def schemas(self) -> list[dict]:
        return [tool.schema() for tool in self._tools.values()]

    def execute(self, name: str, tool_input: dict) -> str:
        tool = self._tools.get(name)
        if tool is None:
            return f"Unknown tool: {name}"
        return tool.handler(tool_input)
