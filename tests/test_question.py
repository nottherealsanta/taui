"""Tests for QuestionTool."""


from taui.tools.builtins.question import (
    QuestionTool,
    _normalize_options,
    _normalize_recommended,
)


class TestQuestionTool:
    def test_schema(self):
        tool = QuestionTool()
        assert tool.name == "question"
        assert "question" in tool.schema["required"]
        # The options schema now describes structured option objects.
        options_schema = tool.schema["properties"]["options"]
        assert options_schema["items"]["type"] == "object"
        assert "label" in options_schema["items"]["properties"]
        assert "description" in options_schema["items"]["properties"]
        # `recommended` is a top-level optional integer.
        assert tool.schema["properties"]["recommended"]["type"] == "integer"

    async def test_no_callback(self):
        tool = QuestionTool()
        result = await tool.execute({"question": "What color?"})
        assert not result.error
        assert "best judgment" in result.content

    async def test_with_callback(self):
        tool = QuestionTool()
        tool._ask = self._make_ask("blue")
        result = await tool.execute({"question": "What color?"})
        assert not result.error
        assert "blue" in result.content
        assert result.metadata["answered"] is True

    async def test_callback_returns_none(self):
        tool = QuestionTool()
        tool._ask = self._make_ask(None)
        result = await tool.execute({"question": "What color?"})
        assert not result.error
        assert "dismissed" in result.content
        assert result.metadata["answered"] is False

    async def test_empty_question_fails(self):
        tool = QuestionTool()
        result = await tool.execute({"question": ""})
        assert result.error

    async def test_missing_question_fails(self):
        tool = QuestionTool()
        result = await tool.execute({})
        assert result.error

    async def test_with_structured_options_and_recommended(self):
        tool = QuestionTool()
        captured = {}

        async def ask(question, options, recommended):
            captured["options"] = options
            captured["recommended"] = recommended
            return options[recommended - 1]["label"]

        tool._ask = ask
        result = await tool.execute({
            "question": "Pick a color",
            "options": [
                {"label": "red", "description": "warm"},
                {"label": "blue", "description": "cool"},
                {"label": "green"},
            ],
            "recommended": 2,
        })
        assert "blue" in result.content
        assert captured["recommended"] == 2
        # Options preserve description (gray detail) and label.
        assert captured["options"][0] == {"label": "red", "description": "warm"}
        assert captured["options"][2] == {"label": "green", "description": None}

    async def test_string_options_back_compat(self):
        tool = QuestionTool()
        captured = {}

        async def ask(question, options, recommended):
            captured["options"] = options
            captured["recommended"] = recommended
            return options[0]["label"]

        tool._ask = ask
        result = await tool.execute({
            "question": "Pick a color",
            "options": ["red", "blue", "green"],
        })
        assert "red" in result.content
        assert captured["options"][0]["label"] == "red"
        assert captured["recommended"] is None

    async def test_recommended_by_label(self):
        tool = QuestionTool()
        captured = {}

        async def ask(question, options, recommended):
            captured["recommended"] = recommended
            return options[recommended - 1]["label"]

        tool._ask = ask
        await tool.execute({
            "question": "Pick a color",
            "options": [{"label": "red"}, {"label": "blue"}],
            "recommended": "blue",
        })
        assert captured["recommended"] == 2

    async def test_recommended_out_of_range_ignored(self):
        tool = QuestionTool()
        captured = {}

        async def ask(question, options, recommended):
            captured["recommended"] = recommended
            return "ok"

        tool._ask = ask
        await tool.execute({
            "question": "Pick",
            "options": [{"label": "a"}, {"label": "b"}],
            "recommended": 99,
        })
        assert captured["recommended"] is None

    async def test_legacy_recommended_suffix(self):
        """Labels ending in '(recommended)' get stripped + flagged."""
        tool = QuestionTool()
        captured = {}

        async def ask(question, options, recommended):
            captured["options"] = options
            captured["recommended"] = recommended
            return options[0]["label"]

        tool._ask = ask
        await tool.execute({
            "question": "Pick",
            "options": ["fast (Recommended)", "slow"],
        })
        assert captured["recommended"] == 1
        assert captured["options"][0]["label"] == "fast"

    async def test_legacy_two_arg_callback(self):
        """Older callbacks that only accept (question, options) still work."""
        tool = QuestionTool()
        captured = {}

        async def ask(question, options):
            captured["options"] = options
            return options[0] if options else None

        tool._ask = ask
        result = await tool.execute({
            "question": "Pick",
            "options": [{"label": "red"}, {"label": "blue"}],
            "recommended": 2,
        })
        # Legacy options are flat strings with "(Recommended)" suffix.
        assert "(Recommended)" in captured["options"][1]
        assert "red" in result.content

    @staticmethod
    def _make_ask(answer):
        async def ask(question, options, recommended):
            return answer
        return ask


class TestNormalizeHelpers:
    def test_normalize_options_strings(self):
        out = _normalize_options(["a", "b"])
        assert out == [
            {"label": "a", "description": None},
            {"label": "b", "description": None},
        ]

    def test_normalize_options_dicts(self):
        out = _normalize_options(
            [{"label": "a", "description": "x"}, {"label": "b"}]
        )
        assert out == [
            {"label": "a", "description": "x"},
            {"label": "b", "description": None},
        ]

    def test_normalize_options_drops_empty(self):
        out = _normalize_options(["", {"label": ""}, "ok"])
        assert out == [{"label": "ok", "description": None}]

    def test_normalize_options_non_list(self):
        assert _normalize_options("not a list") is None
        assert _normalize_options(None) is None

    def test_normalize_recommended_int(self):
        opts = [{"label": "a", "description": None}]
        assert _normalize_recommended(1, opts) == 1
        assert _normalize_recommended(2, opts) is None

    def test_normalize_recommended_str(self):
        opts = [{"label": "Alpha", "description": None}, {"label": "Beta", "description": None}]
        assert _normalize_recommended("beta", opts) == 2
        assert _normalize_recommended("missing", opts) is None

    def test_normalize_recommended_none(self):
        opts = [{"label": "a", "description": None}]
        assert _normalize_recommended(None, opts) is None
