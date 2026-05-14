"""Tests for QuestionTool."""


from taui.tools.builtins.question import QuestionTool


class TestQuestionTool:
    def test_schema(self):
        tool = QuestionTool()
        assert tool.name == "question"
        assert "question" in tool.schema["required"]

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

    async def test_with_options(self):
        tool = QuestionTool()
        tool._ask = self._make_ask("red")
        result = await tool.execute({
            "question": "Pick a color",
            "options": ["red", "blue", "green"],
        })
        assert "red" in result.content

    @staticmethod
    def _make_ask(answer):
        async def ask(question, options):
            return answer
        return ask
