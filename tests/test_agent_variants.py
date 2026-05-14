"""Tests for named agent variants."""

from taui.agent.variants import AgentVariant, AgentVariantRegistry


class TestAgentVariant:
    def test_default_values(self):
        v = AgentVariant(name="test")
        assert v.name == "test"
        assert v.model is None
        assert v.tool_names is None
        assert not v.read_only

    def test_read_only(self):
        v = AgentVariant(name="plan", read_only=True)
        assert v.read_only


class TestAgentVariantRegistry:
    def test_builtins_registered(self):
        reg = AgentVariantRegistry()
        assert "build" in reg.names()
        assert "plan" in reg.names()

    def test_get_builtin(self):
        reg = AgentVariantRegistry()
        build = reg.get("build")
        assert build is not None
        assert build.name == "build"

    def test_plan_is_read_only(self):
        reg = AgentVariantRegistry()
        plan = reg.get("plan")
        assert plan is not None
        assert plan.read_only

    def test_register_custom(self):
        reg = AgentVariantRegistry()
        reg.register(AgentVariant(name="review", description="Code review"))
        assert "review" in reg.names()
        assert reg.get("review").description == "Code review"

    def test_unregister(self):
        reg = AgentVariantRegistry()
        reg.register(AgentVariant(name="temp"))
        reg.unregister("temp")
        assert reg.get("temp") is None

    def test_discover_from_dir(self, tmp_path):
        agents_dir = tmp_path / ".taui" / "agents"
        agents_dir.mkdir(parents=True)
        (agents_dir / "review.toml").write_text(
            'name = "review"\ndescription = "Code reviewer"\nread_only = true\n'
        )
        reg = AgentVariantRegistry()
        loaded = reg.discover_from_dir(agents_dir)
        assert "review" in loaded
        v = reg.get("review")
        assert v.read_only
        assert v.description == "Code reviewer"

    def test_discover_empty_dir(self, tmp_path):
        reg = AgentVariantRegistry()
        loaded = reg.discover_from_dir(tmp_path / "nonexistent")
        assert loaded == []

    def test_all(self):
        reg = AgentVariantRegistry()
        assert len(reg.all()) >= 2
