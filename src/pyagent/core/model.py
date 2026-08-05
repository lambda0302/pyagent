"""LLM 客户端接口与 OpenAI 兼容实现。

:class:`LLMClient` 抽象基类是预留的接缝：v2 可以在不触碰 agent 循环的前提下
接入其他供应商（Anthropic、Ollama 等）。
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from collections.abc import Callable
from dataclasses import dataclass, field

from pyagent.config import ModelConfig


class ModelError(Exception):
    """模型调用失败时抛出（网络、鉴权、异常响应等）。"""


@dataclass
class ToolCall:
    """模型请求的一个函数调用。"""

    id: str
    name: str
    arguments: str  # 原始 JSON 对象字符串


@dataclass
class LLMResponse:
    """一次完整的模型响应：文本和/或工具调用。"""

    content: str | None = None
    tool_calls: list[ToolCall] = field(default_factory=list)
    usage: dict | None = None

    @property
    def has_tool_calls(self) -> bool:
        return bool(self.tool_calls)


#: 模型流式输出文本增量时调用的回调。
DeltaFn = Callable[[str], None]


class LLMClient(ABC):
    """agent 循环所对话的统一接口。"""

    @abstractmethod
    def complete(
        self,
        messages: list[dict],
        tools: list[dict] | None = None,
        stream: bool = False,
        on_delta: DeltaFn | None = None,
    ) -> LLMResponse:
        """执行一次模型调用。

        Args:
            messages: OpenAI 风格的消息列表。
            tools: 工具 schema 列表（OpenAI 的 ``tools`` 格式），可选。
            stream: 为 True 时把文本增量喂给 ``on_delta``。
            on_delta: 流式文本增量的可选回调。
        """


class OpenAILLMClient(LLMClient):
    """OpenAI 兼容的对话补全客户端（使用 ``openai`` 包）。"""

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
        except ImportError as exc:  # pragma: no cover - 环境问题
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

        # 流式：一边转发文本增量，一边累积完整响应。
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
    """去掉孤立的代理字符（例如流式过程中 UTF-8 被切断产生的），否则会
    破坏 JSON 序列化。用 U+FFFD 替换。"""
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
    """描述 agent 职责与工具用法的系统提示词。"""
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
