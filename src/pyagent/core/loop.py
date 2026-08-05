"""The main agent loop: messages ↔ tool calls until a final answer.

Flow per turn:
    assemble/compress messages → call model → if tool calls requested, execute
    each and feed results back → call model again → ... until the model replies
    with text (or the turn budget is exhausted).
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from pyagent.core.context import ContextManager
from pyagent.core.messages import Session
from pyagent.core.model import LLMClient, LLMResponse, ToolCall, build_system_prompt
from pyagent.tools.permissions import PermissionManager
from pyagent.tools.registry import ToolContext, ToolRegistry


@dataclass
class LoopStats:
    turns: int = 0
    tool_calls: int = 0
    total_tokens: int = 0


class AgentLoop:
    def __init__(
        self,
        llm: LLMClient,
        registry: ToolRegistry,
        config,
        session: Session,
        cwd: Path,
        permissions: PermissionManager | None = None,
        context: ContextManager | None = None,
        renderer=None,
    ):
        self.llm = llm
        self.registry = registry
        self.config = config
        self.session = session
        self.cwd = Path(cwd)
        self.permissions = permissions or PermissionManager()
        self.context = context or ContextManager(llm=llm)
        self.renderer = renderer
        self.stats = LoopStats()

    def run(self, prompt: str | None = None) -> str:
        """Run the loop.  Returns the final assistant text."""
        if prompt:
            self.session.append_user(prompt)
        self.session.set_system(build_system_prompt(str(self.cwd)))

        max_turns = self.config.model.max_turns
        for _ in range(max_turns):
            self.stats.turns += 1

            # Context compression before the call keeps history bounded.
            messages = self.session.messages
            if self.context.should_compress(messages):
                self.session.messages = self.context.compress(messages)

            response = self._call_model()
            self._track_usage(response)

            if not response.has_tool_calls:
                self.session.append_assistant(response.content)
                if self.renderer is not None:
                    self.renderer.on_final(response.content or "")
                return response.content or ""

            # Model wants tools: record the request, run each call, feed results.
            self.session.append_assistant(
                response.content,
                tool_calls=[_to_api_tool_call(tc) for tc in response.tool_calls],
            )
            for tc in response.tool_calls:
                self.stats.tool_calls += 1
                if self.renderer is not None:
                    self.renderer.on_tool_start(tc.name, _preview_args(tc.arguments))
                result = self.registry.execute(tc.name, tc.arguments, self._tool_context())
                if self.renderer is not None:
                    self.renderer.on_tool_result(result)
                self.session.append_tool_result(tc.id, tc.name, result.content)

        final = (
            f"[Reached the {max_turns}-turn limit without a final answer. "
            "The task may need more steps or fewer tool calls.]"
        )
        self.session.append_assistant(final)
        if self.renderer is not None:
            self.renderer.on_final(final)
        return final

    def _call_model(self) -> LLMResponse:
        messages = self.session.messages
        if self.renderer is not None and hasattr(self.renderer, "on_assistant_delta"):
            return self.llm.complete(
                messages,
                tools=self.registry.openai_schemas(),
                stream=True,
                on_delta=self.renderer.on_assistant_delta,
            )
        return self.llm.complete(messages, tools=self.registry.openai_schemas())

    def _tool_context(self) -> ToolContext:
        return ToolContext(
            cwd=self.cwd,
            config=self.config,
            permissions=self.permissions,
            renderer=self.renderer,
        )

    def _track_usage(self, response: LLMResponse) -> None:
        if response.usage and response.usage.get("total_tokens"):
            self.stats.total_tokens += response.usage["total_tokens"]


def _to_api_tool_call(tc: ToolCall) -> dict:
    return {
        "id": tc.id,
        "type": "function",
        "function": {"name": tc.name, "arguments": tc.arguments},
    }


def _preview_args(arguments_json: str, max_len: int = 80) -> str:
    compact = arguments_json.strip()
    if len(compact) > max_len:
        compact = compact[: max_len - 3] + "..."
    return compact
