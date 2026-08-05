"""B1: agent loop logic under a mock model.  B3: context compression."""

from __future__ import annotations

import json
from pathlib import Path

from conftest import MockLLMClient
from pyagent.config import Config
from pyagent.core.context import ContextManager
from pyagent.core.loop import AgentLoop
from pyagent.core.messages import Session
from pyagent.core.model import LLMResponse, ToolCall
from pyagent.tools.permissions import PermissionManager
from pyagent.tools.registry import build_default_registry


def _make_loop(llm, config, cwd: Path, session=None, **kw) -> AgentLoop:
    return AgentLoop(
        llm=llm,
        registry=build_default_registry(),
        config=config,
        session=session or Session(session_id="test"),
        cwd=cwd,
        permissions=PermissionManager(),
        **kw,
    )


def _tool_response(name="write_file", arguments=None) -> LLMResponse:
    if arguments is None:
        arguments = json.dumps({"path": "hello.txt", "content": "hello agent"})
    return LLMResponse(tool_calls=[ToolCall(id="call_1", name=name, arguments=arguments)])


class TestLoopToolUse:
    def test_tool_call_executed_then_model_requeried(self, tmp_path):
        """① model requests a tool → tool executes → result fed back → model called again."""
        llm = MockLLMClient(
            [
                _tool_response(),
                LLMResponse(content="File created."),
            ]
        )
        loop = _make_loop(llm, Config(), tmp_path)
        result = loop.run(prompt="create a file hello.txt with 'hello agent'")

        assert result == "File created."
        assert (tmp_path / "hello.txt").read_text(encoding="utf-8") == "hello agent"
        # model called twice; second call carries the tool result message
        assert llm.calls_count == 2
        second_messages = llm.calls[1][0]
        tool_msgs = [m for m in second_messages if m["role"] == "tool"]
        assert tool_msgs and tool_msgs[0]["name"] == "write_file"
        assert "hello.txt" in tool_msgs[0]["content"]
        # the assistant tool_calls request is present in history for the API
        assistant_msgs = [m for m in second_messages if m["role"] == "assistant"]
        assert any("tool_calls" in m for m in assistant_msgs)

    def test_direct_reply_terminates(self, tmp_path):
        """② model replies with text → loop terminates after one call."""
        llm = MockLLMClient([LLMResponse(content="hi")])
        loop = _make_loop(llm, Config(), tmp_path)
        result = loop.run(prompt="say hi")
        assert result == "hi"
        assert llm.calls_count == 1

    def test_max_turns_terminates(self, tmp_path):
        """③ model never gives a final answer → loop stops at max_turns."""
        config = Config()
        config.model.max_turns = 2
        llm = MockLLMClient([_tool_response(), _tool_response()])
        loop = _make_loop(llm, config, tmp_path)
        result = loop.run(prompt="keep going")
        assert "limit" in result.lower()
        assert llm.calls_count == 2

    def test_tool_error_is_fed_back_to_model(self, tmp_path):
        """A failing tool returns an error message the model can read."""
        bad = _tool_response(name="read_file", arguments=json.dumps({"path": "nope.txt"}))
        llm = MockLLMClient([bad, LLMResponse(content="The file does not exist.")])
        loop = _make_loop(llm, Config(), tmp_path)
        result = loop.run(prompt="read nope.txt")
        assert "does not exist" in result
        tool_msgs = [m for m in loop.session.messages if m["role"] == "tool"]
        assert tool_msgs and "Error" in tool_msgs[0]["content"]


class TestContextCompression:
    def _long_messages(self) -> list[dict]:
        system = {"role": "system", "content": "you are pyagent"}
        pairs = [
            {"role": "user", "content": "goal: fix bug in module 0"},
            {"role": "assistant", "content": "let me investigate " + ("x" * 500)},
        ]
        for i in range(10):
            pairs.append({"role": "user", "content": f"step {i}: " + "y" * 300})
            pairs.append({"role": "assistant", "content": f"ok step {i} done " + "z" * 200})
        return [system] + pairs

    def test_should_compress_flags_long_history(self):
        mgr = ContextManager(llm=MockLLMClient([]), max_history_chars=1000, min_keep=6)
        assert mgr.should_compress(self._long_messages())

    def test_compress_preserves_summary_and_tail(self):
        llm = MockLLMClient([LLMResponse(content="SUMMARY: goal 'fix bug in module 0' preserved; steps 0-9 done")])
        messages = self._long_messages()
        mgr = ContextManager(llm=llm, max_history_chars=1000, min_keep=6)
        compressed = mgr.compress(messages)

        assert len(compressed) < len(messages)
        # key info survives in the summary
        summary = [m for m in compressed if m.get("_summary")][0]
        assert "fix bug in module 0" in summary["content"]
        # system prompt stays first
        assert compressed[0]["role"] == "system"
        # tail (active exchange) preserved verbatim
        assert compressed[-len(messages[-6 :]) :] == messages[-6:]
        # the summary LLM was invoked for summarisation
        assert llm.calls_count == 1

    def test_short_history_is_not_touched(self):
        messages = [{"role": "system", "content": "s"}, {"role": "user", "content": "hi"}]
        mgr = ContextManager(llm=MockLLMClient([]), max_history_chars=1000, min_keep=6)
        assert mgr.compress(messages) == messages

    def test_loop_still_works_with_compression_enabled(self, tmp_path):
        """B3: after compression the loop keeps calling the model normally."""
        config = Config()
        llm = MockLLMClient([LLMResponse(content="final answer after compression")])
        loop = _make_loop(llm, config, tmp_path)
        # force compression on the very first call
        loop.context = ContextManager(llm=llm, max_history_chars=0, min_keep=1)
        loop.run(prompt="tell me something")
        assert llm.calls_count >= 1
