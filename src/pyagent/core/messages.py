"""会话历史：消息组装、保存、加载、恢复。

会话以「一个会话一个 JSON 文件」的形式存放在配置的会话目录下。内存中的历史
是 OpenAI 风格的消息列表，可直接传给 LLM 客户端。
"""

from __future__ import annotations

import json
import uuid
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path


@dataclass
class Session:
    """带持久化历史的一个聊天会话。"""

    session_id: str
    messages: list[dict] = field(default_factory=list)
    created_at: str = field(default_factory=lambda: _now())
    updated_at: str = field(default_factory=lambda: _now())
    title: str = "untitled"

    # -- 持久化 -----------------------------------------------------
    def save(self, session_dir: str | Path) -> Path:
        """把会话写入 ``session_dir/<id>.json`` 并返回路径。"""
        directory = Path(session_dir)
        directory.mkdir(parents=True, exist_ok=True)
        self.updated_at = _now()
        path = directory / f"{self.session_id}.json"
        payload = {
            "session_id": self.session_id,
            "created_at": self.created_at,
            "updated_at": self.updated_at,
            "title": self.title,
            "messages": self.messages,
        }
        with open(path, "w", encoding="utf-8") as fh:
            json.dump(_clean(payload), fh, ensure_ascii=False, indent=2)
        return path

    @classmethod
    def load(cls, session_dir: str | Path, session_id: str) -> Session:
        """按 id 加载会话；不存在时抛出 ``FileNotFoundError``。"""
        path = Path(session_dir) / f"{session_id}.json"
        with open(path, encoding="utf-8") as fh:
            payload = json.load(fh)
        return cls(
            session_id=payload["session_id"],
            messages=payload.get("messages", []),
            created_at=payload.get("created_at", _now()),
            updated_at=payload.get("updated_at", _now()),
            title=payload.get("title", "untitled"),
        )

    # -- 消息组装 ---------------------------------------------------
    def append_user(self, text: str) -> None:
        self.messages.append({"role": "user", "content": _clean(text)})

    def append_assistant(self, content: str | None, tool_calls: list | None = None) -> None:
        message: dict = {"role": "assistant", "content": content or ""}
        if tool_calls:
            message["tool_calls"] = tool_calls
        self.messages.append(message)

    def append_tool_result(self, tool_call_id: str, name: str, content: str) -> None:
        self.messages.append(
            {
                "role": "tool",
                "tool_call_id": tool_call_id,
                "name": name,
                "content": content,
            }
        )

    def set_system(self, system_prompt: str) -> None:
        """确保第一条消息是系统提示词（恢复会话时去重）。"""
        if self.messages and self.messages[0].get("role") == "system":
            self.messages[0] = {"role": "system", "content": system_prompt}
        else:
            self.messages.insert(0, {"role": "system", "content": system_prompt})

    def set_summary(self, summary: str) -> None:
        """在系统消息之后替换/插入一条滚动上下文摘要。"""
        summary_msg = {"role": "system", "content": f"[context summary of earlier turns]\n{summary}"}
        if self.messages and self.messages[0].get("role") == "system":
            # 丢弃旧的摘要槽位，再插入新的
            self.messages = [m for m in self.messages if not m.get("_summary")]
            self.messages.insert(1, summary_msg | {"_summary": True})
        else:
            self.messages.insert(0, summary_msg | {"_summary": True})


def _clean(obj: object):
    """递归地把孤立的代理字符替换成 U+FFFD（JSON 安全网）。"""
    if isinstance(obj, str):
        return obj.encode("utf-8", errors="replace").decode("utf-8")
    if isinstance(obj, dict):
        return {k: _clean(v) for k, v in obj.items()}
    if isinstance(obj, list):
        return [_clean(v) for v in obj]
    return obj


def _now() -> str:
    return datetime.now().strftime("%Y-%m-%dT%H:%M:%S")


def new_session_id() -> str:
    return datetime.now().strftime("%Y%m%d-%H%M%S") + "-" + uuid.uuid4().hex[:6]


def list_sessions(session_dir: str | Path) -> list[dict]:
    """返回所有已保存会话的元数据，最新的在前。"""
    directory = Path(session_dir)
    if not directory.exists():
        return []
    entries: list[dict] = []
    for path in directory.glob("*.json"):
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            continue
        entries.append(
            {
                "session_id": payload.get("session_id", path.stem),
                "title": payload.get("title", "untitled"),
                "updated_at": payload.get("updated_at", ""),
                "message_count": len(payload.get("messages", [])),
                "path": str(path),
            }
        )
    entries.sort(key=lambda e: e["updated_at"], reverse=True)
    return entries
