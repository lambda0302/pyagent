"""LLM client interface and the OpenAI-compatible implementation.

The :class:`LLMClient` ABC is the seam that lets v2 plug in other providers
(Anthropic, Ollama, ...) without touching the agent loop.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from collections.abc import Callable
from dataclasses import dataclass, field

from pyagent.config import ModelConfig


class ModelError(Exception):
    """Raised when a model call fails (network, auth, bad response, ...)."""


@dataclass
class ToolCall:
    """A function call requested by the model."""

    id: str
    name: str
    arguments: str  # raw JSON object string


@dataclass
class LLMResponse:
    """A complete model response: text and/or tool calls."""

    content: str | None = None
    tool_calls: list[ToolCall] = field(default_factory=list)
    usage: dict | None = None

    @property
    def has_tool_calls(self) -> bool:
        return bool(self.tool_calls)


#: Callback receiving a text delta as the model streams a response.
DeltaFn = Callable[[str], None]


class LLMClient(ABC):
    """Uniform interface the agent loop talks to."""

    @abstractmethod
    def complete(
        self,
        messages: list[dict],
        tools: list[dict] | None = None,
        stream: bool = False,
        on_delta: DeltaFn | None = None,
    ) -> LLMResponse:
        """Run one model call.

        Args:
            messages: OpenAI-style message list.
            tools: tool schema list (OpenAI ``tools`` format), optional.
            stream: when True, feed text deltas to ``on_delta``.
            on_delta: optional callback for streamed text deltas.
        """


class OpenAILLMClient(LLMClient):
    """OpenAI-compatible chat completions client (uses the ``openai`` package)."""

    def __init__(self, config: ModelConfig, tool_schemas: list[dict] | None = None):
        self.config = config
        self.tool_schemas = tool_schemas or []
        api_key = config.resolve_api_key()
        if not api_key:
            raise ModelError(
                f"no API key found: set the {config.api_key_env!r} environment variable "
                "(or configure model/api_key_env in the TOML)."
            )
        try:
            from openai import OpenAI
        except ImportError as exc:  # pragma: no cover - env issue
            raise ModelError("the 'openai' package is not installed; run `pip install openai`") from exc
        self._client = OpenAI(api_key=api_key, base_url=config.base_url, timeout=config.timeout)

    def complete(
        self,
        messages: list[dict],
        tools: list[dict] | None = None,
        stream: bool = False,
        on_delta: DeltaFn | None = None,
    ) -> LLMResponse:
        kwargs: dict = {"model": self.config.model, "messages": messages}
        if tools:
            kwargs["tools"] = tools
        if not stream:
            resp = self._client.chat.completions.create(**kwargs)
            return _parse_response(resp)

        # Streaming: accumulate the response while forwarding text deltas.
        tool_calls: dict[int, dict] = {}
        content_parts: list[str] = []
        usage: dict | None = None
        try:
            stream_resp = self._client.chat.completions.create(stream=True, **kwargs)
            for chunk in stream_resp:
                if not chunk.choices:
                    if chunk.usage:
                        usage = _serialise_usage(chunk.usage)
                    continue
                delta = chunk.choices[0].delta
                if delta is None:
                    continue
                if delta.content:
                    clean = _clean_text(delta.content)
                    content_parts.append(clean)
                    if on_delta:
                        on_delta(clean)
                if delta.tool_calls:
                    for tc in delta.tool_calls:
                        slot = tool_calls.setdefault(
                            tc.index, {"id": "", "name": "", "arguments": ""}
                        )
                        if tc.id:
                            slot["id"] = tc.id
                        if tc.function and tc.function.name:
                            slot["name"] += tc.function.name
                        if tc.function and tc.function.arguments:
                            slot["arguments"] += tc.function.arguments
        except Exception as exc:
            raise ModelError(f"model call failed: {exc}") from exc

        calls = [
            ToolCall(
                id=slot["id"] or f"call_{i}",
                name=slot["name"],
                arguments=_clean_text(slot["arguments"]),
            )
            for i, slot in sorted(tool_calls.items())
        ]
        return LLMResponse(
            content=_clean_text("".join(content_parts)) or None,
            tool_calls=calls,
            usage=usage,
        )


def _parse_response(resp: object) -> LLMResponse:
    msg = resp.choices[0].message
    calls = [
        ToolCall(
            id=tc.id,
            name=tc.function.name,
            arguments=_clean_text(tc.function.arguments or "{}"),
        )
        for tc in (msg.tool_calls or [])
    ]
    usage = getattr(resp, "usage", None)
    return LLMResponse(
        content=_clean_text(msg.content),
        tool_calls=calls,
        usage=_serialise_usage(usage) if usage else None,
    )


def _clean_text(text: str | None) -> str | None:
    """Strip lone surrogates (e.g. from a mid-stream UTF-8 split) that would
    otherwise crash JSON serialisation.  Replaces them with U+FFFD."""
    if text is None:
        return None
    return text.encode("utf-8", errors="replace").decode("utf-8")


def _serialise_usage(usage: object) -> dict:
    return {
        "prompt_tokens": getattr(usage, "prompt_tokens", None),
        "completion_tokens": getattr(usage, "completion_tokens", None),
        "total_tokens": getattr(usage, "total_tokens", None),
    }


def build_system_prompt(cwd: str) -> str:
    """The system prompt that describes the agent's job and tool usage."""
    return (
        "You are pyagent, a coding agent that works autonomously in a local "
        "terminal. You accomplish user tasks by thinking, calling tools "
        "(read_file, write_file, edit_file, glob, grep, bash), observing the "
        "results, and continuing until the task is complete, then you give a "
        "final answer.\n\n"
        "Rules:\n"
        "- Only use tools you are given; every tool call returns a text result.\n"
        "- You may make several tool calls in one turn when they are independent.\n"
        "- read before you edit: use read_file to inspect a file before changing it.\n"
        "- When a tool result is an error (e.g. denied by the user, file not "
        "found), adapt and tell the user what happened.\n"
        "- Prefer the smallest change that satisfies the request.\n"
        f"- Working directory: {cwd}. Use paths relative to it.\n"
        "- Reply in the same language the user used.\n"
    )
