"""上下文窗口管理：通过摘要压缩过长的历史。

借鉴 keen-code 的 "TurnMemory" 思路：不再让历史无限增长，而是把较早的轮次
折叠进一条滚动摘要，以系统消息的形式注入。摘要保留与目标相关的关键信息
（任务、文件路径、决策、阻塞点），让模型能继续工作。
"""

from __future__ import annotations

import json
from dataclasses import dataclass

from pyagent.core.model import LLMClient, LLMResponse

#: 序列化历史超过该字节数时触发压缩。
DEFAULT_MAX_HISTORY_CHARS = 40_000

#: 始终保留的消息条数下限（当前活跃的交流）。
_MIN_KEEP_MESSAGES = 6

_SUMMARISE_PROMPT = (
    "You are compressing a long agent conversation. Read the conversation and "
    "write a concise summary that preserves: the user's goal and requirements, "
    "file paths that were created or modified and what changed, decisions made, "
    "and any open problems or next steps. Keep it under 300 words. Output only "
    "the summary, no preamble."
)


@dataclass
class ContextManager:
    """当 ``Session`` 历史超过大小阈值时对其进行压缩。"""

    llm: LLMClient
    max_history_chars: int = DEFAULT_MAX_HISTORY_CHARS
    min_keep: int = _MIN_KEEP_MESSAGES

    def should_compress(self, messages: list[dict]) -> bool:
        total = sum(len(json.dumps(m, ensure_ascii=False)) for m in messages)
        return total > self.max_history_chars

    def compress(self, messages: list[dict]) -> list[dict]:
        """把较早的消息折叠进摘要；返回新的消息列表。

        摘要是由配置的 LLM 生成的（唯一需要真实推理的部分），因此测试中
        可以用 mock 客户端验证整个流程。
        """
        if len(messages) <= self.min_keep:
            return messages

        # 拆分：system（+已有的摘要）保留；尾部原样保留；中间部分被摘要。
        head: list[dict] = []
        body: list[dict] = []
        tail: list[dict] = messages[-self.min_keep :]

        idx = 0
        if messages and messages[0].get("role") == "system":
            head.append(messages[0])
            idx = 1
            # 顺带带上之前已有的摘要消息
            if idx < len(messages) and messages[idx].get("_summary"):
                head.append(messages[idx])
                idx += 1
        body = messages[idx:-self.min_keep] if self.min_keep else messages[idx:]

        if not body:
            return messages

        summary = self._summarise(body)

        # 重建：head（system + 旧摘要）... 新摘要 ... 尾部。
        kept_head = [m for m in head if not m.get("_summary")]
        result: list[dict] = kept_head
        if summary:
            result.append({"role": "system", "content": f"[context summary]\n{summary}", "_summary": True})
        result.extend(tail)
        return result

    def _summarise(self, messages: list[dict]) -> str:
        conv = "\n\n".join(
            f"{m.get('role').upper()}: {m.get('content') or ''}" for m in messages
        )
        if not conv.strip():
            return ""
        try:
            response: LLMResponse = self.llm.complete(
                [
                    {"role": "system", "content": _SUMMARISE_PROMPT},
                    {"role": "user", "content": conv},
                ]
            )
            return (response.content or "").strip()
        except Exception:
            # 摘要是尽力而为的：绝不能让它在循环中导致崩溃。
            return ""
