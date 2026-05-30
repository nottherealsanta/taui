"""Tests for taui.skills.installer — source parsing and installation."""

from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

from taui.skills import (
    SkillInstallError,
    install,
    looks_like_skill_source,
    parse_source,
    parse_sources,
)
from taui.skills.installer import (
    find_skill_dirs,
    parse_scope_flags,
    skills_root,
    strip_runner_prefix,
)

# ═══ Prefix / scope stripping ═════════════════════════════════════════════════


class TestStripRunnerPrefix:
    @pytest.mark.parametrize(
        "spec,expected",
        [
            ("npx skills add owner/repo", "owner/repo"),
            ("skills add owner/repo", "owner/repo"),
            ("pnpm dlx skills add owner/repo", "owner/repo"),
            ("yarn skills add owner/repo", "owner/repo"),
            ("bunx skills add owner/repo", "owner/repo"),
            ("  npx   skills   add   owner/repo  ", "owner/repo"),
            ("owner/repo", "owner/repo"),  # no prefix
        ],
    )
    def test_strip(self, spec: str, expected: str):
        assert strip_runner_prefix(spec) == expected


class TestParseScopeFlags:
    def test_global_flag(self):
        spec, scope = parse_scope_flags("owner/repo -g")
        assert spec == "owner/repo"
        assert scope == "global"

    def test_long_global_flag(self):
        spec, scope = parse_scope_flags("--global owner/repo")
        assert spec == "owner/repo"
        assert scope == "global"

    def test_project_flag(self):
        spec, scope = parse_scope_flags("owner/repo --project")
        assert spec == "owner/repo"
        assert scope == "project"

    def test_no_flag(self):
        spec, scope = parse_scope_flags("owner/repo")
        assert spec == "owner/repo"
        assert scope is None


# ═══ Source parsing ═══════════════════════════════════════════════════════════


class TestParseSource:
    def test_github_shorthand(self):
        src = parse_source("vercel-labs/agent-skills")
        assert src.kind == "git"
        assert src.url == "https://github.com/vercel-labs/agent-skills.git"
        assert src.subpath == ""
        assert src.ref is None

    def test_github_shorthand_with_subpath(self):
        src = parse_source("owner/repo/skills/web-design")
        assert src.url == "https://github.com/owner/repo.git"
        assert src.subpath == "skills/web-design"

    def test_github_shorthand_strips_git_suffix(self):
        src = parse_source("owner/repo.git")
        assert src.url == "https://github.com/owner/repo.git"

    def test_full_github_url(self):
        src = parse_source("https://github.com/vercel-labs/agent-skills")
        assert src.url == "https://github.com/vercel-labs/agent-skills.git"
        assert src.subpath == ""

    def test_github_tree_url(self):
        src = parse_source(
            "https://github.com/vercel-labs/agent-skills/tree/main/skills/foo"
        )
        assert src.url == "https://github.com/vercel-labs/agent-skills.git"
        assert src.ref == "main"
        assert src.subpath == "skills/foo"

    def test_github_blob_url(self):
        src = parse_source("https://github.com/o/r/blob/dev/skills/x")
        assert src.ref == "dev"
        assert src.subpath == "skills/x"

    def test_gitlab_tree_url(self):
        src = parse_source("https://gitlab.com/org/repo/-/tree/release/skills/y")
        assert src.url == "https://gitlab.com/org/repo.git"
        assert src.ref == "release"
        assert src.subpath == "skills/y"

    def test_ssh_git_url(self):
        src = parse_source("git@github.com:vercel-labs/agent-skills.git")
        assert src.kind == "git"
        assert src.url == "git@github.com:vercel-labs/agent-skills.git"
        assert src.ref is None

    def test_local_relative_path(self):
        src = parse_source("./my-skills")
        assert src.kind == "local"
        assert src.local_path == Path("my-skills")

    def test_local_absolute_path(self):
        src = parse_source("/abs/path/skills")
        assert src.kind == "local"
        assert src.local_path == Path("/abs/path/skills")

    def test_file_url(self):
        src = parse_source("file:///tmp/foo")
        assert src.kind == "local"
        assert src.local_path == Path("/tmp/foo")

    def test_empty_raises(self):
        with pytest.raises(SkillInstallError):
            parse_source("")

    def test_unrecognized_raises(self):
        with pytest.raises(SkillInstallError):
            parse_source("just-one-word")


class TestParseSources:
    def test_with_npx_prefix_and_flag(self):
        sources, scope = parse_sources("npx skills add owner/repo -g")
        assert scope == "global"
        assert len(sources) == 1
        assert sources[0].url == "https://github.com/owner/repo.git"

    def test_multiple_whitespace(self):
        sources, _ = parse_sources("owner/a owner/b")
        assert [s.url for s in sources] == [
            "https://github.com/owner/a.git",
            "https://github.com/owner/b.git",
        ]

    def test_multiple_comma(self):
        sources, _ = parse_sources("owner/a, owner/b")
        assert len(sources) == 2

    def test_empty_raises(self):
        with pytest.raises(SkillInstallError):
            parse_sources("npx skills add")


# ═══ looks_like_skill_source ══════════════════════════════════════════════════


class TestLooksLikeSkillSource:
    @pytest.mark.parametrize(
        "text",
        [
            "npx skills add owner/repo",
            "skills add owner/repo",
            "owner/repo",
            "vercel-labs/agent-skills",
            "https://github.com/owner/repo",
            "git@github.com:owner/repo.git",
            "owner/repo/skills/foo",
        ],
    )
    def test_positive(self, text: str):
        assert looks_like_skill_source(text) is True

    @pytest.mark.parametrize(
        "text",
        [
            "",
            "please install owner/repo for me",  # multi-token free text
            "fix the bug in src/main.py",
            "src/main.py",  # looks like a file
            "/skills add owner/repo",  # slash command
            "./local/path",  # bare local path is not auto-detected
            "just some words\nover two lines",
            "hello world",
            "README.md",
        ],
    )
    def test_negative(self, text: str):
        assert looks_like_skill_source(text) is False


# ═══ find_skill_dirs ══════════════════════════════════════════════════════════


class TestFindSkillDirs:
    def test_root_is_skill(self, tmp_path: Path):
        (tmp_path / "SKILL.md").write_text("x", encoding="utf-8")
        assert find_skill_dirs(tmp_path) == [tmp_path.resolve()]

    def test_nested_skills(self, tmp_path: Path):
        for name in ("foo", "bar"):
            d = tmp_path / "skills" / name
            d.mkdir(parents=True)
            (d / "SKILL.md").write_text("x", encoding="utf-8")
        found = {p.name for p in find_skill_dirs(tmp_path)}
        assert found == {"foo", "bar"}

    def test_does_not_descend_into_skill(self, tmp_path: Path):
        d = tmp_path / "outer"
        (d / "inner").mkdir(parents=True)
        (d / "SKILL.md").write_text("x", encoding="utf-8")
        (d / "inner" / "SKILL.md").write_text("y", encoding="utf-8")
        found = find_skill_dirs(tmp_path)
        assert found == [(tmp_path / "outer").resolve()]

    def test_skips_dot_dirs(self, tmp_path: Path):
        d = tmp_path / ".git" / "hooks"
        d.mkdir(parents=True)
        (d / "SKILL.md").write_text("x", encoding="utf-8")
        assert find_skill_dirs(tmp_path) == []

    def test_none_found(self, tmp_path: Path):
        (tmp_path / "README.md").write_text("x", encoding="utf-8")
        assert find_skill_dirs(tmp_path) == []


# ═══ skills_root ══════════════════════════════════════════════════════════════


def test_skills_root_project(tmp_path: Path):
    assert skills_root(tmp_path, "project") == tmp_path / ".taui" / "skills"


def test_skills_root_global(tmp_path: Path):
    home = tmp_path / "home"
    assert skills_root(tmp_path, "global", home=home) == home / ".taui" / "skills"


# ═══ Installation (local + git) ═══════════════════════════════════════════════


def _make_skill(root: Path, dirname: str, *, name: str | None = None, body: str = "go"):
    d = root / dirname
    d.mkdir(parents=True, exist_ok=True)
    front = ""
    if name is not None:
        front = f"---\nname: {name}\ndescription: desc\n---\n"
    (d / "SKILL.md").write_text(f"{front}# Skill\n{body}\n", encoding="utf-8")
    return d


def _make_git_repo(root: Path) -> Path:
    repo = root / "repo"
    _make_skill(repo / "skills", "foo", name="foo-skill")
    _make_skill(repo / "skills", "bar", name="bar-skill")
    subprocess.run(["git", "init", "-q", str(repo)], check=True)
    subprocess.run(["git", "-C", str(repo), "add", "-A"], check=True)
    subprocess.run(
        ["git", "-C", str(repo), "-c", "user.email=t@t",
         "-c", "user.name=t", "commit", "-qm", "init"],
        check=True,
    )
    return repo


class TestInstallLocal:
    def test_install_repo_finds_all_skills(self, tmp_path: Path):
        src = tmp_path / "src"
        _make_skill(src / "skills", "foo", name="foo-skill")
        _make_skill(src / "skills", "bar", name="bar-skill")
        work = tmp_path / "work"

        result = install(str(src), working_dir=work, scope="project")
        assert result.ok
        assert {s.name for s in result.installed} == {"foo-skill", "bar-skill"}
        assert (work / ".taui" / "skills" / "foo-skill" / "SKILL.md").is_file()

    def test_install_single_skill_dir(self, tmp_path: Path):
        src = tmp_path / "src"
        _make_skill(src, "only", name="only-skill")
        work = tmp_path / "work"

        result = install(str(src / "only"), working_dir=work, scope="project")
        assert [s.name for s in result.installed] == ["only-skill"]

    def test_frontmatter_name_wins_over_dirname(self, tmp_path: Path):
        src = tmp_path / "src"
        _make_skill(src, "weird-dir", name="clean-name")
        work = tmp_path / "work"

        result = install(str(src / "weird-dir"), working_dir=work, scope="project")
        assert result.installed[0].name == "clean-name"

    def test_dirname_used_without_frontmatter(self, tmp_path: Path):
        src = tmp_path / "src"
        _make_skill(src, "plain", name=None)
        work = tmp_path / "work"

        result = install(str(src / "plain"), working_dir=work, scope="project")
        assert result.installed[0].name == "plain"

    def test_overwrite_marks_updated(self, tmp_path: Path):
        src = tmp_path / "src"
        _make_skill(src, "dup", name="dup")
        work = tmp_path / "work"

        install(str(src / "dup"), working_dir=work, scope="project")
        result = install(str(src / "dup"), working_dir=work, scope="project")
        assert result.installed[0].overwritten is True

    def test_global_scope(self, tmp_path: Path):
        src = tmp_path / "src"
        _make_skill(src, "g", name="g-skill")
        home = tmp_path / "home"

        result = install(
            str(src / "g"),
            working_dir=tmp_path / "work",
            scope="global",
            home=home,
        )
        assert result.scope == "global"
        assert (home / ".taui" / "skills" / "g-skill" / "SKILL.md").is_file()

    def test_global_flag_overrides_scope(self, tmp_path: Path):
        src = tmp_path / "src"
        _make_skill(src, "g", name="g-skill")
        home = tmp_path / "home"

        result = install(
            f"npx skills add {src / 'g'} -g",
            working_dir=tmp_path / "work",
            scope="project",
            home=home,
        )
        assert result.scope == "global"

    def test_no_skills_found(self, tmp_path: Path):
        src = tmp_path / "src"
        src.mkdir()
        (src / "README.md").write_text("nope", encoding="utf-8")

        result = install(str(src), working_dir=tmp_path / "work", scope="project")
        assert not result.ok
        assert "No SKILL.md" in result.summary()

    def test_missing_local_path_raises(self, tmp_path: Path):
        with pytest.raises(SkillInstallError):
            install(str(tmp_path / "nope"), working_dir=tmp_path, scope="project")


class TestInstallGit:
    def test_clone_whole_repo(self, tmp_path: Path):
        repo = _make_git_repo(tmp_path)
        work = tmp_path / "work"

        result = install(f"file://{repo}", working_dir=work, scope="project")
        assert {s.name for s in result.installed} == {"foo-skill", "bar-skill"}

    def test_clone_subpath(self, tmp_path: Path):
        repo = _make_git_repo(tmp_path)
        work = tmp_path / "work"

        result = install(
            f"file://{repo}/skills/foo", working_dir=work, scope="project"
        )
        assert [s.name for s in result.installed] == ["foo-skill"]

    def test_clone_bad_subpath_raises(self, tmp_path: Path):
        repo = _make_git_repo(tmp_path)
        with pytest.raises(SkillInstallError):
            install(
                f"file://{repo}/skills/nope",
                working_dir=tmp_path / "work",
                scope="project",
            )
