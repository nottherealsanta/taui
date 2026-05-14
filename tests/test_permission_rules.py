"""Sandbox tests for PermissionRuleset — pattern matching and layer cascade."""

from __future__ import annotations

from taui.permissions import PermissionRuleset
from taui.tools.executor import PolicyDecision


class TestPatternMatching:
    def test_exact_match(self):
        rs = PermissionRuleset()
        rs.add_rules({"bash": {"git status": "allow"}})
        assert rs.decide("bash", "git status") == PolicyDecision.AUTO

    def test_wildcard_match(self):
        rs = PermissionRuleset()
        rs.add_rules({"bash": {"*": "ask"}})
        assert rs.decide("bash", "anything") == PolicyDecision.CONFIRM

    def test_glob_pattern(self):
        rs = PermissionRuleset()
        rs.add_rules({"read": {"src/**": "allow", "*.env": "ask"}})
        assert rs.decide("read", "src/main.py") == PolicyDecision.AUTO
        assert rs.decide("read", ".env") == PolicyDecision.CONFIRM

    def test_no_match_returns_none(self):
        rs = PermissionRuleset()
        rs.add_rules({"bash": {"git *": "allow"}})
        assert rs.decide("read", "foo.py") is None

    def test_deny_action(self):
        rs = PermissionRuleset()
        rs.add_rules({"bash": {"rm -rf *": "deny"}})
        assert rs.decide("bash", "rm -rf /") == PolicyDecision.DENY


class TestSpecificityOrder:
    def test_specific_overrides_wildcard(self):
        """More specific patterns should win over wildcards."""
        rs = PermissionRuleset()
        rs.add_rules({"read": {
            "*": "ask",
            "*.env": "deny",
            ".env.example": "allow",
        }})
        # .env.example matches both "*.env" and ".env.example"
        # .env.example is more specific (longer non-wildcard)
        assert rs.decide("read", ".env.example") == PolicyDecision.AUTO
        assert rs.decide("read", ".env") == PolicyDecision.DENY
        assert rs.decide("read", "foo.py") == PolicyDecision.CONFIRM

    def test_longer_pattern_wins(self):
        rs = PermissionRuleset()
        rs.add_rules({"bash": {
            "*": "ask",
            "git status": "allow",
        }})
        assert rs.decide("bash", "git status") == PolicyDecision.AUTO
        assert rs.decide("bash", "git push") == PolicyDecision.CONFIRM


class TestLayerCascade:
    def test_agent_overrides_project(self):
        rs = PermissionRuleset()
        rs.add_rules({"bash": {"*": "ask"}}, layer="project")
        rs.add_rules({"bash": {"*": "allow"}}, layer="agent")
        assert rs.decide("bash", "anything") == PolicyDecision.AUTO

    def test_project_overrides_global(self):
        rs = PermissionRuleset()
        rs.add_rules({"bash": {"*": "ask"}}, layer="global")
        rs.add_rules({"bash": {"*": "allow"}}, layer="project")
        assert rs.decide("bash", "anything") == PolicyDecision.AUTO

    def test_agent_layer_checked_first(self):
        rs = PermissionRuleset()
        rs.add_rules({"read": {"*.env": "deny"}}, layer="global")
        rs.add_rules({"read": {"*.env": "allow"}}, layer="agent")
        assert rs.decide("read", ".env") == PolicyDecision.AUTO

    def test_fallthrough_to_global(self):
        """No agent or project rules → falls through to global."""
        rs = PermissionRuleset()
        rs.add_rules({"edit": {"*": "ask"}}, layer="global")
        assert rs.decide("edit", "foo.py") == PolicyDecision.CONFIRM

    def test_no_rules_returns_none(self):
        rs = PermissionRuleset()
        assert rs.decide("bash", "ls") is None


class TestSubjectExtraction:
    def test_bash_uses_command(self):
        rs = PermissionRuleset()
        subject = rs.extract_subject("bash", {"command": "git status"})
        assert subject == "git status"

    def test_read_uses_file_path(self):
        rs = PermissionRuleset()
        subject = rs.extract_subject("read", {"file_path": "src/main.py"})
        assert subject == "src/main.py"

    def test_read_uses_filePath(self):
        rs = PermissionRuleset()
        subject = rs.extract_subject("read", {"filePath": "src/main.py"})
        assert subject == "src/main.py"

    def test_glob_uses_pattern(self):
        rs = PermissionRuleset()
        subject = rs.extract_subject("glob", {"pattern": "*.py"})
        assert subject == "*.py"

    def test_unknown_tool_returns_empty(self):
        rs = PermissionRuleset()
        subject = rs.extract_subject("unknown_tool", {"x": "y"})
        assert subject == ""


class TestClearLayer:
    def test_clear_project(self):
        rs = PermissionRuleset()
        rs.add_rules({"bash": {"*": "allow"}}, layer="project")
        assert rs.decide("bash", "ls") == PolicyDecision.AUTO
        rs.clear_layer("project")
        assert rs.decide("bash", "ls") is None

    def test_clear_agent(self):
        rs = PermissionRuleset()
        rs.add_rules({"bash": {"*": "deny"}}, layer="agent")
        rs.clear_layer("agent")
        assert rs.decide("bash", "ls") is None


class TestAllRules:
    def test_all_rules_returns_combined(self):
        rs = PermissionRuleset()
        rs.add_rules({"bash": {"*": "allow"}}, layer="agent")
        rs.add_rules({"read": {"*": "ask"}}, layer="project")
        all_rules = rs.all_rules
        assert len(all_rules) == 2
        tools = {r.tool for r in all_rules}
        assert tools == {"bash", "read"}
