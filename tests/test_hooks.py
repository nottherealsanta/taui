"""Tests for taui.hooks — HookRegistry."""

from __future__ import annotations

import pytest

from taui.hooks import HookRegistry


class TestHookRegistration:
    def test_add_and_has(self):
        hooks = HookRegistry()
        hooks.add("test", lambda: None)
        assert hooks.has("test")
        assert not hooks.has("nope")

    def test_convenience_methods(self):
        hooks = HookRegistry()
        hooks.prompt(lambda s: "> ")
        hooks.banner(lambda s: "hi")
        hooks.status(lambda s: "ok")
        hooks.turn_summary(lambda r, s: "done")
        hooks.before_send(lambda m, s: m)
        hooks.after_result(lambda r, s: r)
        hooks.system_prompt(lambda p, s: p)
        hooks.on_tool_call(lambda n, a, s: None)
        hooks.on_tool_result(lambda n, c, e, s: None)
        hooks.on_session_start(lambda s: None)
        hooks.on_mode_change(lambda m, s: None)
        hooks.on_approval(lambda n, a, s: True)
        assert hooks.count("prompt") == 1
        assert hooks.count("on_approval") == 1
        assert len(hooks.hook_names) == 12

    def test_count(self):
        hooks = HookRegistry()
        assert hooks.count("test") == 0
        hooks.add("test", lambda: 1)
        hooks.add("test", lambda: 2)
        assert hooks.count("test") == 2


class TestHookExecution:
    async def test_run_sync(self):
        hooks = HookRegistry()
        hooks.add("test", lambda x: x * 2)
        results = await hooks.run("test", 5)
        assert results == [10]

    async def test_run_async(self):
        hooks = HookRegistry()

        async def double(x):
            return x * 2

        hooks.add("test", double)
        results = await hooks.run("test", 5)
        assert results == [10]

    async def test_run_multiple(self):
        hooks = HookRegistry()
        hooks.add("test", lambda x: x + 1)
        hooks.add("test", lambda x: x + 2)
        results = await hooks.run("test", 10)
        assert results == [11, 12]

    async def test_run_empty(self):
        hooks = HookRegistry()
        results = await hooks.run("nothing")
        assert results == []

    async def test_run_error_skipped(self):
        hooks = HookRegistry()
        hooks.add("test", lambda: 1 / 0)
        hooks.add("test", lambda: 42)
        results = await hooks.run("test")
        assert results == [42]

    async def test_collect_filters_none(self):
        hooks = HookRegistry()
        hooks.add("test", lambda: None)
        hooks.add("test", lambda: "hello")
        hooks.add("test", lambda: None)
        hooks.add("test", lambda: "world")
        results = await hooks.collect("test")
        assert results == ["hello", "world"]


class TestHookTransform:
    async def test_transform_pipeline(self):
        hooks = HookRegistry()
        hooks.add("pipe", lambda val: val + " world")
        hooks.add("pipe", lambda val: val + "!")
        result = await hooks.transform("pipe", "hello")
        assert result == "hello world!"

    async def test_transform_empty(self):
        hooks = HookRegistry()
        result = await hooks.transform("pipe", "unchanged")
        assert result == "unchanged"

    async def test_transform_async(self):
        hooks = HookRegistry()

        async def add_suffix(val):
            return val + "-async"

        hooks.add("pipe", add_suffix)
        result = await hooks.transform("pipe", "test")
        assert result == "test-async"

    async def test_transform_error_skipped(self):
        hooks = HookRegistry()
        hooks.add("pipe", lambda val: val + " first")
        hooks.add("pipe", lambda val: 1 / 0)  # error
        hooks.add("pipe", lambda val: val + " third")
        # After error, val stays at "hello first", then " third" appended
        result = await hooks.transform("pipe", "hello")
        assert result == "hello first third"

    async def test_transform_with_extra_args(self):
        hooks = HookRegistry()
        hooks.add("pipe", lambda val, ctx: f"{val} ({ctx})")
        result = await hooks.transform("pipe", "msg", "context")
        assert result == "msg (context)"


class TestHookFirst:
    async def test_first_returns_first_non_none(self):
        hooks = HookRegistry()
        hooks.add("test", lambda: None)
        hooks.add("test", lambda: "found")
        hooks.add("test", lambda: "ignored")
        result = await hooks.first("test")
        assert result == "found"

    async def test_first_all_none(self):
        hooks = HookRegistry()
        hooks.add("test", lambda: None)
        result = await hooks.first("test")
        assert result is None

    async def test_first_empty(self):
        hooks = HookRegistry()
        result = await hooks.first("test")
        assert result is None

    async def test_first_async(self):
        hooks = HookRegistry()

        async def check():
            return True

        hooks.add("test", check)
        result = await hooks.first("test")
        assert result is True

    async def test_first_error_skipped(self):
        hooks = HookRegistry()
        hooks.add("test", lambda: 1 / 0)
        hooks.add("test", lambda: "fallback")
        result = await hooks.first("test")
        assert result == "fallback"
