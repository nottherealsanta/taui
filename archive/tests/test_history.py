from __future__ import annotations

import asyncio
from pathlib import Path

import pytest

from taui.history.db import HistoryDB


def _run(coro):
    return asyncio.run(coro)


class TestHistoryDB:
    def test_connect_creates_db_file(self, tmp_path: Path) -> None:
        db_path = tmp_path / "history.db"

        async def go():
            db = HistoryDB(db_path=db_path)
            await db.connect()
            await db.close()

        _run(go())
        assert db_path.exists()

    def test_record_session_and_list(self, tmp_path: Path) -> None:
        db_path = tmp_path / "history.db"

        async def go():
            db = HistoryDB(db_path=db_path)
            await db.connect()

            await db.record_session(
                agent_id="agent-1",
                workspace="/home/user/project",
                spec_ref="root/overview",
                task="Write the overview",
                display_name="Atlas",
                model="claude-sonnet-4.6",
                agent_type="root",
            )

            sessions = await db.list_sessions()
            assert len(sessions) == 1
            s = sessions[0]
            assert s["agent_id"] == "agent-1"
            assert s["workspace"] == "/home/user/project"
            assert s["spec_ref"] == "root/overview"
            assert s["task"] == "Write the overview"
            assert s["display_name"] == "Atlas"

            await db.close()

        _run(go())

    def test_record_messages_and_get(self, tmp_path: Path) -> None:
        db_path = tmp_path / "history.db"

        async def go():
            db = HistoryDB(db_path=db_path)
            await db.connect()

            await db.record_session(
                agent_id="agent-1",
                workspace="/tmp/ws",
                spec_ref="root",
                task="test task",
            )

            await db.record_message(
                agent_id="agent-1", role="system", content="You are an agent."
            )
            await db.record_message(
                agent_id="agent-1", role="user", content="Hello"
            )
            await db.record_message(
                agent_id="agent-1", role="assistant", content="Hi there"
            )

            msgs = await db.get_messages("agent-1")
            assert len(msgs) == 3
            assert msgs[0]["role"] == "system"
            assert msgs[0]["seq"] == 1
            assert msgs[1]["role"] == "user"
            assert msgs[1]["seq"] == 2
            assert msgs[2]["role"] == "assistant"
            assert msgs[2]["content"] == "Hi there"
            assert msgs[2]["seq"] == 3

            await db.close()

        _run(go())

    def test_list_sessions_filters_by_workspace(self, tmp_path: Path) -> None:
        db_path = tmp_path / "history.db"

        async def go():
            db = HistoryDB(db_path=db_path)
            await db.connect()

            await db.record_session(
                agent_id="a1",
                workspace="/ws1",
                spec_ref="root",
                task="task1",
            )
            await db.record_session(
                agent_id="a2",
                workspace="/ws2",
                spec_ref="root",
                task="task2",
            )

            all_sessions = await db.list_sessions()
            assert len(all_sessions) == 2

            ws1_sessions = await db.list_sessions(workspace="/ws1")
            assert len(ws1_sessions) == 1
            assert ws1_sessions[0]["agent_id"] == "a1"

            await db.close()

        _run(go())

    def test_duplicate_session_ignored(self, tmp_path: Path) -> None:
        db_path = tmp_path / "history.db"

        async def go():
            db = HistoryDB(db_path=db_path)
            await db.connect()

            await db.record_session(
                agent_id="a1",
                workspace="/ws",
                spec_ref="root",
                task="task1",
            )
            # Same agent_id again — should be silently ignored
            await db.record_session(
                agent_id="a1",
                workspace="/ws",
                spec_ref="root",
                task="different task",
            )

            sessions = await db.list_sessions()
            assert len(sessions) == 1
            assert sessions[0]["task"] == "task1"

            await db.close()

        _run(go())

    def test_messages_with_tool_call_fields(self, tmp_path: Path) -> None:
        db_path = tmp_path / "history.db"

        async def go():
            db = HistoryDB(db_path=db_path)
            await db.connect()

            await db.record_session(
                agent_id="a1",
                workspace="/ws",
                spec_ref="root",
                task="tool test",
            )
            await db.record_message(
                agent_id="a1",
                role="tool",
                content='{"result": "ok"}',
                tool_call_id="call_123",
                name="bash",
            )

            msgs = await db.get_messages("a1")
            assert len(msgs) == 1
            assert msgs[0]["tool_call_id"] == "call_123"
            assert msgs[0]["name"] == "bash"

            await db.close()

        _run(go())

    def test_connect_idempotent(self, tmp_path: Path) -> None:
        db_path = tmp_path / "history.db"

        async def go():
            db = HistoryDB(db_path=db_path)
            await db.connect()
            await db.connect()  # should be no-op
            await db.record_session(
                agent_id="a1",
                workspace="/ws",
                spec_ref="root",
                task="task",
            )
            sessions = await db.list_sessions()
            assert len(sessions) == 1
            await db.close()

        _run(go())

    def test_close_idempotent(self, tmp_path: Path) -> None:
        db_path = tmp_path / "history.db"

        async def go():
            db = HistoryDB(db_path=db_path)
            await db.connect()
            await db.close()
            await db.close()  # should be no-op

        _run(go())

    def test_parent_dir_created(self, tmp_path: Path) -> None:
        db_path = tmp_path / "nested" / "dir" / "history.db"

        async def go():
            db = HistoryDB(db_path=db_path)
            await db.connect()
            await db.close()

        _run(go())
        assert db_path.exists()
