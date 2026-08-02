"""Generic tool-calling agent loop shared by all tabularius agents.

Not the Hermes agent system — a purpose-built loop that drives an LLM
through JSON outputs and optional tool calls until it produces a
schema-valid answer. Every agent role (memory / recall / index /
reader) runs on this loop with its own system prompt and tool set.
"""

from __future__ import annotations

import json
from typing import Any, Callable, TypeVar, cast

from pydantic import BaseModel

from tabularius.llm import LLMClient
from tabularius.schemas import SchemaParseError, parse_or_retry
from tabularius.tools import TOOL_REGISTRY

MAX_SCHEMA_RETRIES = 2
MAX_TOOL_ROUNDS = 25

DispatchFn = Callable[[str, dict[str, Any]], str]

T = TypeVar("T", bound=BaseModel)


def _default_dispatch(name: str, args: dict[str, Any]) -> str:
    """Look up a tool in the registry and call it, returning its JSON result."""
    tool = TOOL_REGISTRY.get(name)
    if tool is None:
        return json.dumps({"ok": False, "error": f"unknown tool: {name}"})
    return tool(**args)


def run_agent(
    system: str,
    user: str,
    tools: list[dict[str, Any]],
    schema: type[T],
    *,
    client: LLMClient | None = None,
    dispatch: DispatchFn | None = None,
    timeout: float | None = None,
    max_schema_retries: int = MAX_SCHEMA_RETRIES,
    max_tool_rounds: int = MAX_TOOL_ROUNDS,
) -> T:
    """Run the tool-calling loop until the model returns schema-valid JSON.

    - messages = [system, user]
    - while True:
        - llm.chat(messages, tools, json_object)
        - if tool_calls: execute each via ``dispatch``, append the
          assistant tool_call message (OpenAI requirement) followed by
          tool result messages, continue.
        - else: return schema-validated JSON.
    - Schema violations retry up to ``max_schema_retries`` times,
      appending the parse error as corrective feedback.
    """
    llm = client or LLMClient()
    dispatch = dispatch or _default_dispatch
    messages: list[dict[str, Any]] = [
        {"role": "system", "content": system},
        {"role": "user", "content": user},
    ]
    schema_failures = 0

    for _ in range(max_tool_rounds + 1):
        response = llm.chat(messages, tools=tools, timeout=timeout)
        if not response.choices:
            raise RuntimeError("llm returned a response with no choices")
        message = response.choices[0].message

        if message.tool_calls:
            # OpenAI rule: echo the assistant's tool_call message before
            # the tool results, with matching tool_call_id.
            messages.append(message.model_dump(exclude_none=True))
            for call in message.tool_calls:
                name = call.function.name
                try:
                    args = json.loads(call.function.arguments or "{}")
                except json.JSONDecodeError:
                    args = {}
                try:
                    result = dispatch(name, args)
                except Exception as exc:  # tool failures feed back to the model
                    result = json.dumps({"ok": False, "error": f"{name}: {exc}"})
                messages.append({"role": "tool", "tool_call_id": call.id, "content": result})
            continue

        content = message.content or ""
        try:
            return cast(T, parse_or_retry(content, schema))
        except SchemaParseError as exc:
            if schema_failures >= max_schema_retries:
                raise
            schema_failures += 1
            messages.append(
                {
                    "role": "user",
                    "content": (
                        "Your previous output did not match the required JSON "
                        f"schema: {exc}\n"
                        "Fix the output and return ONLY valid JSON matching the schema."
                    ),
                }
            )

    raise RuntimeError(f"agent loop exceeded {max_tool_rounds} tool rounds without a final answer")
