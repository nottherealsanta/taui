"""Install skills from external sources — vercel-labs/skills compatible.

Parses the source formats accepted by ``npx skills add`` and installs the
discovered ``SKILL.md`` packages into taui's skill directories:

  - GitHub shorthand:          ``owner/repo``
  - Shorthand with subpath:    ``owner/repo/skills/web-design``
  - Full GitHub URL:           ``https://github.com/owner/repo``
  - URL pointing at a skill:   ``https://github.com/owner/repo/tree/main/skills/foo``
  - GitLab URL:                ``https://gitlab.com/org/repo`` (``/-/tree/ref/path``)
  - Generic / SSH git URL:     ``git@github.com:owner/repo.git``
  - Local filesystem path:     ``./my-skills`` or ``/abs/path``

The leading ``npx skills add`` (or ``pnpm``/``yarn``/``bunx`` variants) is
stripped, and a ``-g``/``--global`` flag selects the global scope.

Skills install to:

  - project scope:  ``<working_dir>/.taui/skills/<name>/``
  - global scope:   ``~/.taui/skills/<name>/``

where ``<name>`` is the skill's frontmatter ``name`` when present, otherwise
its source directory name.
"""

from __future__ import annotations

import logging
import re
import shutil
import subprocess
import tempfile
from dataclasses import dataclass, field
from pathlib import Path

logger = logging.getLogger(__name__)

# Recognised package-runner prefixes that precede ``skills add <source>``.
_RUNNER_RE = re.compile(
    r"^\s*(?:npx|pnpm(?:\s+dlx)?|yarn(?:\s+dlx)?|bunx|bun\s+x)?\s*"
    r"skills\s+add\s+",
    re.IGNORECASE,
)

# Hosts we know how to translate ``/tree/<ref>/<path>`` style web URLs for.
_TREE_SEPARATORS = ("/-/tree/", "/tree/", "/-/blob/", "/blob/", "/src/branch/")

_GIT_SSH_RE = re.compile(r"^[\w.+-]+@[\w.-]+:.+")


class SkillInstallError(Exception):
    """Raised when a source cannot be parsed or installed."""


@dataclass(frozen=True, slots=True)
class SkillSource:
    """A normalized, ready-to-fetch skill source."""

    kind: str                 # "git" or "local"
    raw: str                  # original (post-prefix-strip) spec
    url: str = ""             # clone URL (git)
    ref: str | None = None    # branch / tag / commit (git)
    subpath: str = ""         # path within the repo / local dir to a skill root
    local_path: Path | None = None


@dataclass(slots=True)
class InstalledSkill:
    name: str
    dest: Path
    overwritten: bool = False


@dataclass(slots=True)
class InstallResult:
    source: SkillSource
    scope: str
    installed: list[InstalledSkill] = field(default_factory=list)
    skipped: list[str] = field(default_factory=list)

    @property
    def ok(self) -> bool:
        return bool(self.installed)

    def summary(self) -> str:
        if not self.installed:
            return "No SKILL.md packages found in the source."
        lines = [
            f"Installed {len(self.installed)} skill(s) into {self.scope} scope:"
        ]
        for sk in self.installed:
            tag = " (updated)" if sk.overwritten else ""
            lines.append(f"  - {sk.name}{tag}  →  {sk.dest}")
        if self.skipped:
            lines.append(f"Skipped: {', '.join(self.skipped)}")
        return "\n".join(lines)


# ── Spec parsing ────────────────────────────────────────────────────


def strip_runner_prefix(spec: str) -> str:
    """Remove a leading ``npx skills add`` (or sibling) command prefix."""
    return _RUNNER_RE.sub("", spec.strip()).strip()


def parse_scope_flags(spec: str) -> tuple[str, str | None]:
    """Split scope flags (``-g``/``--global``/``--project``) out of a spec.

    Returns ``(remaining_spec, scope_or_none)``.
    """
    tokens = spec.split()
    scope: str | None = None
    kept: list[str] = []
    for tok in tokens:
        low = tok.lower()
        if low in ("-g", "--global"):
            scope = "global"
        elif low in ("--project", "-p", "--local"):
            scope = "project"
        else:
            kept.append(tok)
    return " ".join(kept), scope


# File extensions that signal a plain path/message rather than a repo ref.
_NON_SKILL_SUFFIXES = (
    ".py", ".js", ".ts", ".tsx", ".jsx", ".md", ".txt", ".json", ".toml",
    ".yaml", ".yml", ".rs", ".go", ".java", ".c", ".cpp", ".h", ".sh",
    ".png", ".jpg", ".jpeg", ".gif", ".csv", ".lock", ".cfg", ".ini",
)

_SHORTHAND_RE = re.compile(r"^[A-Za-z0-9][\w.-]*/[\w.-]+(?:/[\w./-]+)?$")


def looks_like_skill_source(text: str) -> bool:
    """Heuristic: does pasted ``text`` look like a ``skills add`` source?

    Recognizes the ``npx skills add`` family of prefixes, bare git/web URLs,
    SSH git URLs, and unambiguous ``owner/repo`` GitHub shorthand. Multi-line
    or multi-token free text is treated as a normal message (returns False).
    """
    stripped = text.strip()
    if not stripped or "\n" in stripped:
        return False
    if _RUNNER_RE.match(stripped):
        return True
    # Below here we only accept a single bare token (no spaces).
    if len(stripped.split()) != 1:
        return False
    token = stripped
    if "://" in token or _GIT_SSH_RE.match(token):
        return True
    # GitHub shorthand: owner/repo[/subpath], but not a local path or a file.
    if token.startswith((".", "/", "~")):
        return False
    if _SHORTHAND_RE.match(token):
        last = token.rstrip("/").rsplit("/", 1)[-1].lower()
        if any(last.endswith(suffix) for suffix in _NON_SKILL_SUFFIXES):
            return False
        return True
    return False


def parse_source(spec: str) -> SkillSource:
    """Parse a single source spec into a :class:`SkillSource`."""
    raw = spec.strip()
    if not raw:
        raise SkillInstallError("Empty skill source.")

    # Local filesystem paths.
    if raw.startswith((".", "/", "~")) or raw.startswith("file://"):
        path_str = raw[len("file://") :] if raw.startswith("file://") else raw
        path = Path(path_str).expanduser()
        return SkillSource(kind="local", raw=raw, local_path=path)

    # SSH-style git URLs: git@host:owner/repo.git
    if _GIT_SSH_RE.match(raw):
        url, ref, subpath = _split_git_url(raw)
        return SkillSource(kind="git", raw=raw, url=url, ref=ref, subpath=subpath)

    # http(s) / git protocol URLs.
    if "://" in raw:
        url, ref, subpath = _split_web_url(raw)
        return SkillSource(kind="git", raw=raw, url=url, ref=ref, subpath=subpath)

    # GitHub shorthand: owner/repo[/subpath...]
    if "/" in raw:
        parts = [p for p in raw.split("/") if p]
        if len(parts) >= 2:
            owner, repo = parts[0], parts[1]
            repo = repo[:-4] if repo.endswith(".git") else repo
            subpath = "/".join(parts[2:])
            url = f"https://github.com/{owner}/{repo}.git"
            return SkillSource(kind="git", raw=raw, url=url, subpath=subpath)

    raise SkillInstallError(
        f"Could not recognize skill source: {spec!r}. "
        "Use owner/repo, a git URL, or a local path."
    )


def parse_sources(spec: str) -> tuple[list[SkillSource], str | None]:
    """Parse a full user spec into sources plus an optional explicit scope.

    Accepts a ``npx skills add`` prefix, scope flags, and multiple
    whitespace- or comma-separated sources.
    """
    cleaned = strip_runner_prefix(spec)
    cleaned, scope = parse_scope_flags(cleaned)
    cleaned = cleaned.strip().strip(",")
    if not cleaned:
        raise SkillInstallError("No skill source provided.")
    # Split on commas first, then whitespace, so both styles work.
    chunks: list[str] = []
    for piece in cleaned.split(","):
        chunks.extend(piece.split())
    sources = [parse_source(chunk) for chunk in chunks if chunk]
    if not sources:
        raise SkillInstallError("No skill source provided.")
    return sources, scope


def _split_web_url(raw: str) -> tuple[str, str | None, str]:
    """Split a web URL into (clone_url, ref, subpath).

    Handles GitHub/GitLab/Gitea ``/tree/<ref>/<path>`` and ``/blob/`` forms.
    """
    url = raw
    ref: str | None = None
    subpath = ""
    for sep in _TREE_SEPARATORS:
        idx = url.find(sep)
        if idx == -1:
            continue
        base = url[:idx]
        rest = url[idx + len(sep) :]
        rest_parts = [p for p in rest.split("/") if p]
        if rest_parts:
            ref = rest_parts[0]
            subpath = "/".join(rest_parts[1:])
        url = base
        break
    url = url.rstrip("/")
    if not url.endswith(".git"):
        url = url + ".git"
    return url, ref, subpath


def _split_git_url(raw: str) -> tuple[str, str | None, str]:
    """Split an SSH-style git URL; these don't carry web tree paths."""
    url = raw
    if not url.endswith(".git"):
        url = url + ".git"
    return url, None, ""


# ── Installation ────────────────────────────────────────────────────


def skills_root(working_dir: Path, scope: str, home: Path | None = None) -> Path:
    """Destination skills directory for a scope (taui-native)."""
    home = home or Path.home()
    if scope == "project":
        return working_dir / ".taui" / "skills"
    return home / ".taui" / "skills"


def install(
    spec: str,
    *,
    working_dir: Path,
    scope: str = "project",
    home: Path | None = None,
) -> InstallResult:
    """Parse ``spec`` and install every skill it points to.

    ``spec`` may include the ``npx skills add`` prefix and scope flags; an
    explicit ``-g``/``--global`` flag overrides the ``scope`` argument.
    """
    sources, flag_scope = parse_sources(spec)
    effective_scope = flag_scope or scope
    dest_root = skills_root(working_dir, effective_scope, home)

    result = InstallResult(source=sources[0], scope=effective_scope)
    for source in sources:
        _install_one(source, dest_root, result)
    return result


def _install_one(source: SkillSource, dest_root: Path, result: InstallResult) -> None:
    if source.kind == "local":
        assert source.local_path is not None
        root = source.local_path.expanduser()
        if not root.exists():
            raise SkillInstallError(f"Local path does not exist: {root}")
        _install_from_tree(root, dest_root, result)
        return

    with tempfile.TemporaryDirectory(prefix="taui-skill-") as tmp:
        clone_dir = Path(tmp) / "repo"
        _git_clone(source.url, clone_dir, source.ref)
        tree_root = clone_dir
        if source.subpath:
            tree_root = clone_dir / source.subpath
            if not tree_root.exists():
                raise SkillInstallError(
                    f"Path {source.subpath!r} not found in {source.url}."
                )
        _install_from_tree(tree_root, dest_root, result)


def _git_clone(url: str, dest: Path, ref: str | None) -> None:
    """Shallow-clone ``url`` into ``dest``; fall back to full clone for SHAs."""
    base = ["git", "clone", "--depth", "1", "--quiet"]
    attempts: list[list[str]] = []
    if ref:
        attempts.append([*base, "--branch", ref, url, str(dest)])
    attempts.append([*base, url, str(dest)])

    last_err = ""
    for i, cmd in enumerate(attempts):
        try:
            subprocess.run(
                cmd,
                check=True,
                capture_output=True,
                text=True,
                timeout=120,
            )
        except FileNotFoundError as exc:
            raise SkillInstallError("git is not installed or not on PATH.") from exc
        except subprocess.TimeoutExpired as exc:
            raise SkillInstallError(f"git clone timed out: {url}") from exc
        except subprocess.CalledProcessError as exc:
            last_err = (exc.stderr or exc.stdout or "").strip()
            if dest.exists():
                shutil.rmtree(dest, ignore_errors=True)
            continue
        # Clone succeeded. If a ref was requested but --branch failed (this is
        # the non-branch fallback), try to check it out as a commit/tag.
        if ref and i > 0:
            _git_checkout_ref(dest, ref)
        return
    raise SkillInstallError(f"Failed to clone {url}: {last_err or 'unknown error'}")


def _git_checkout_ref(repo: Path, ref: str) -> None:
    """Best-effort checkout of an arbitrary ref after a full clone."""
    try:
        subprocess.run(
            ["git", "-C", str(repo), "fetch", "--depth", "1", "origin", ref],
            check=False,
            capture_output=True,
            text=True,
            timeout=120,
        )
        subprocess.run(
            ["git", "-C", str(repo), "checkout", "--quiet", ref],
            check=True,
            capture_output=True,
            text=True,
            timeout=60,
        )
    except (subprocess.SubprocessError, OSError) as exc:
        raise SkillInstallError(f"Could not check out ref {ref!r}: {exc}") from exc


def _install_from_tree(root: Path, dest_root: Path, result: InstallResult) -> None:
    """Find SKILL.md packages under ``root`` and copy them into ``dest_root``."""
    skill_dirs = find_skill_dirs(root)
    if not skill_dirs:
        return
    dest_root.mkdir(parents=True, exist_ok=True)
    for skill_dir in skill_dirs:
        name = _skill_name(skill_dir)
        dest = dest_root / name
        overwritten = dest.exists()
        if overwritten:
            shutil.rmtree(dest, ignore_errors=True)
        shutil.copytree(skill_dir, dest, ignore=shutil.ignore_patterns(".git"))
        if any(s.name == name for s in result.installed):
            # Same name from two sources/trees — keep the first, note the dup.
            result.skipped.append(name)
            continue
        result.installed.append(
            InstalledSkill(name=name, dest=dest, overwritten=overwritten)
        )


def find_skill_dirs(root: Path) -> list[Path]:
    """Return directories under ``root`` that contain a ``SKILL.md``.

    A directory that is itself a skill is not descended into. ``.git`` and
    other dot-directories are skipped.
    """
    root = root.resolve()
    if (root / "SKILL.md").is_file():
        return [root]
    if not root.is_dir():
        return []

    found: list[Path] = []

    def walk(directory: Path) -> None:
        if (directory / "SKILL.md").is_file():
            found.append(directory)
            return  # don't descend into a skill package
        try:
            entries = sorted(directory.iterdir())
        except OSError:
            return
        for entry in entries:
            if not entry.is_dir():
                continue
            if entry.name.startswith("."):
                continue
            walk(entry)

    walk(root)
    return found


_NAME_RE = re.compile(r"^\s*name\s*:\s*(.+?)\s*$", re.MULTILINE)


def _skill_name(skill_dir: Path) -> str:
    """Prefer the SKILL.md frontmatter ``name``; fall back to the dir name."""
    skill_md = skill_dir / "SKILL.md"
    try:
        text = skill_md.read_text(encoding="utf-8")
    except OSError:
        return _sanitize(skill_dir.name)
    front = _frontmatter(text)
    if front is not None:
        m = _NAME_RE.search(front)
        if m:
            value = m.group(1).strip().strip("\"'")
            if value:
                return _sanitize(value)
    return _sanitize(skill_dir.name)


def _frontmatter(text: str) -> str | None:
    """Return the YAML frontmatter block body, if the file opens with ``---``."""
    if not text.lstrip().startswith("---"):
        return None
    stripped = text.lstrip()
    end = stripped.find("\n---", 3)
    if end == -1:
        return None
    return stripped[3:end]


_SANITIZE_RE = re.compile(r"[^A-Za-z0-9._-]+")


def _sanitize(name: str) -> str:
    cleaned = _SANITIZE_RE.sub("-", name.strip()).strip("-._")
    return cleaned or "skill"
