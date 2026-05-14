"""Tests for permission ruleset DSL."""

from taui.permissions import PermissionRule, PermissionRuleset
from taui.tools.executor import PolicyDecision


class TestPermissionRule:
    def test_specificity(self):
        r1 = PermissionRule(tool="bash", pattern="*", action=PolicyDecision.AUTO)
        r2 = PermissionRule(tool="bash", pattern="git status", action=PolicyDecision.AUTO)
        assert r2.specificity > r1.specificity

    def test_specificity_wildcard(self):
        r = PermissionRule(tool="edit", pattern="src/**", action=PolicyDecision.AUTO)
        assert r.specificity == len("src/")


class TestPermissionRuleset:
    def test_simple_match(self):
        rs = PermissionRuleset()
        rs.add_rules({"bash": {"git status": "allow", "*": "ask"}})
        assert rs.decide("bash", "git status") == PolicyDecision.AUTO
        assert rs.decide("bash", "rm -rf /") == PolicyDecision.CONFIRM

    def test_longest_prefix_wins(self):
        rs = PermissionRuleset()
        rs.add_rules({"edit": {"*": "ask", "src/**": "allow"}})
        assert rs.decide("edit", "src/main.py") == PolicyDecision.AUTO
        assert rs.decide("edit", "config.toml") == PolicyDecision.CONFIRM

    def test_layer_cascade(self):
        rs = PermissionRuleset()
        rs.add_rules({"bash": {"*": "ask"}}, layer="global")
        rs.add_rules({"bash": {"git *": "allow"}}, layer="project")
        # Project layer wins for git commands
        assert rs.decide("bash", "git status") == PolicyDecision.AUTO
        # Global catches the rest
        assert rs.decide("bash", "npm install") == PolicyDecision.CONFIRM

    def test_agent_layer_overrides_all(self):
        rs = PermissionRuleset()
        rs.add_rules({"bash": {"*": "allow"}}, layer="global")
        rs.add_rules({"bash": {"*": "deny"}}, layer="agent")
        assert rs.decide("bash", "anything") == PolicyDecision.DENY

    def test_no_match_returns_none(self):
        rs = PermissionRuleset()
        rs.add_rules({"bash": {"git *": "allow"}})
        assert rs.decide("edit", "file.py") is None

    def test_deny_action(self):
        rs = PermissionRuleset()
        rs.add_rules({"bash": {"rm *": "deny", "*": "ask"}})
        assert rs.decide("bash", "rm -rf /") == PolicyDecision.DENY

    def test_extract_subject(self):
        rs = PermissionRuleset()
        assert rs.extract_subject("bash", {"command": "ls"}) == "ls"
        assert rs.extract_subject("edit", {"file_path": "a.py"}) == "a.py"
        assert rs.extract_subject("read", {"path": "b.py"}) == "b.py"

    def test_clear_layer(self):
        rs = PermissionRuleset()
        rs.add_rules({"bash": {"*": "deny"}}, layer="agent")
        assert rs.decide("bash", "x") == PolicyDecision.DENY
        rs.clear_layer("agent")
        assert rs.decide("bash", "x") is None

    def test_all_rules(self):
        rs = PermissionRuleset()
        rs.add_rules({"bash": {"*": "ask"}}, layer="global")
        rs.add_rules({"edit": {"*": "allow"}}, layer="project")
        assert len(rs.all_rules) == 2
