# Publishing Taui

Use this checklist when publishing a new Taui release to PyPI.

Release metadata lives in `pyproject.toml:3`; the console script entry point is
`pyproject.toml:35`; `--version` is handled by `taui/main.py:65`.

## 1. Bump And Commit Version

Update the version in:

- `pyproject.toml:3`
- `uv.lock:689`
- `AGENTS.md:11`

Then verify and commit:

```bash
uv run python -m pytest tests/ -q
uv run python -c 'from taui.main import main; main(["--version"])'
git add pyproject.toml uv.lock taui/main.py AGENTS.md
git commit -m "Bump version to <version>"
```

## 2. Set PyPI Token

Store the PyPI token in `.env`:

```bash
PYPI_TOKEN=pypi-...
```

Do not print or commit the token.

## 3. Publish From A Clean Worktree

If the main checkout has unstaged work, publish from a temporary worktree at the release
commit:

```bash
VERSION=<version>
COMMIT=$(git rev-parse --short HEAD)
WORKTREE=/private/tmp/taui-publish-$VERSION-$COMMIT

git worktree add --detach "$WORKTREE" HEAD
cd "$WORKTREE"
```

Build and validate artifacts:

```bash
uv build --clear
uv run --with twine twine check dist/*
```

Upload to PyPI using the token from the repo `.env`:

```bash
source /Users/santa/repos/taui/.env
uv publish --token "$PYPI_TOKEN" dist/*
```

Verify PyPI sees the new release:

```bash
uv run --with pip pip index versions taui
```

Clean up the temporary worktree:

```bash
cd /Users/santa/repos/taui
git worktree remove "$WORKTREE"
```

## Notes

- PyPI versions are immutable. If a version was uploaded with a problem, bump to the next
  patch version and publish again.
- Build from a clean release commit, not a dirty checkout, so the artifact matches the
  committed source.
- Full `ruff check .` may currently report existing lint debt outside the release bump.
