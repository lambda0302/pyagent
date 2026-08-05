"""Context window management: compress long histories via summarisation.

Mirrors the "TurnMemory" idea from keen-code: instead of letting the history
grow without bound, older turns are folded into a running summary that is
injected as a system message.  The summary preserves goal-relevant facts
(task, file paths, decisions, blockers) so the model can keep working.
"""

from __future__ import annotations

import json
from dataclasses import dataclass

from pyagent.core.model import LLMClient, LLMResponse

#: Rough upper bound on a serialised history before we compress.
DEFAULT_MAX_HISTORY_CHARS = 40_000

#: Always keep at least this many trailing messages (the active exchange).
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
    """Compresses ``Session`` history when it grows past a size threshold."""

    llm: LLMClient
    max_history_chars: int = DEFAULT_MAX_HISTORY_CHARS
    min_keep: int = _MIN_KEEP_MESSAGES

    def should_compress(self, messages: list[dict]) -> bool:
        total = sum(len(json.dumps(m, ensure_ascii=False)) for m in messages)
        return total > self.max_history_chars

    def compress(self, messages: list[dict]) -> list[dict]:
        """Fold older messages into a summary; return the new message list.

        The summary is produced by the configured LLM (the only piece that
        needs real inference), so in tests a mock client can verify the flow.
        """
        if len(messages) <= self.min_keep:
            return messages

        # Split: system (+existing summary) stays; the tail stays verbatim;
        # the middle is summarised.
        head: list[dict] = []
        body: list[dict] = []
        tail: list[dict] = messages[-self.min_keep :]

        idx = 0
        if messages and messages[0].get("role") == "system":
            head.append(messages[0])
            idx = 1
            # carry over any previous summary message
            if idx < len(messages) and messages[idx].get("_summary"):
                head.append(messages[idx])
                idx += 1
        body = messages[idx:-self.min_keep] if self.min_keep else messages[idx:]

        if not body:
            return messages

        summary = self._summarise(body)

        # Rebuild: head (system + old summary) ... new summary ... tail.
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
            # Summarisation is best-effort: never crash the loop over it.
            return ""
