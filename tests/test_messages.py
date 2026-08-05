"""F1–F3（会话）：保存到磁盘、往返加载、列出元数据。"""

from __future__ import annotations

from pyagent.core.messages import Session, list_sessions, new_session_id


class TestSessionPersistence:
    def test_save_then_load_roundtrip(self, tmp_path):
        session = Session(session_id="abc-123", title="my session")
        session.append_user("create a file")
        session.append_assistant("done", tool_calls=[{"id": "c1", "type": "function"}])
        session.append_tool_result("c1", "bash", "ok")

        saved = session.save(tmp_path)
        assert saved.exists()
        assert saved.name == "abc-123.json"

        loaded = Session.load(tmp_path, "abc-123")
        assert loaded.session_id == "abc-123"
        assert loaded.title == "my session"
        assert len(loaded.messages) == 3
        assert loaded.messages[0]["role"] == "user"
        assert loaded.messages[2]["role"] == "tool"

    def test_load_missing_raises(self, tmp_path):
        try:
            Session.load(tmp_path, "ghost")
            raise AssertionError("expected FileNotFoundError")
        except FileNotFoundError:
            pass

    def test_list_sessions_newest_first(self, tmp_path):
        Session(session_id="old").save(tmp_path)
        Session(session_id="new").save(tmp_path)
        ids = [e["session_id"] for e in list_sessions(tmp_path)]
        assert set(ids) == {"old", "new"}
        # "new" 最后保存 → 按 updated_at 排在最前
        assert ids[0] == "new"

    def test_set_system_dedupes(self):
        session = Session(session_id="s")
        session.set_system("prompt v1")
        session.set_system("prompt v2")
        assert session.messages[0]["content"] == "prompt v2"
        assert session.messages[0]["role"] == "system"
        assert len(session.messages) == 1

    def test_new_session_id_unique(self):
        assert new_session_id() != new_session_id()

    def test_save_survives_lone_surrogates(self, tmp_path):
        """孤立代理字符（流式时 UTF-8 被切断产生）不得让保存崩溃。"""
        session = Session(session_id="surrogate")
        session.messages = [{"role": "assistant", "content": "bad \udc80 char"}]
        session.save(tmp_path)
        loaded = Session.load(tmp_path, "surrogate")
        assert "\udc80" not in loaded.messages[0]["content"]
