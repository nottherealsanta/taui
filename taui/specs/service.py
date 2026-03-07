from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Iterable

from .errors import SpecNotFoundError, SpecServiceError, SpecValidationError
from .markdown import (
    Heading,
    extract_document_title_and_description,
    extract_headings,
    extract_intent_text,
    extract_status,
    find_intent_line,
    parse_markdown_link,
    section_end_index,
    slugify,
)
from .models import SpecNode, SpecNodeDetail, SpecNodePatch, SpecUpdateResult, UNSET


@dataclass(slots=True)
class _SpecRef:
    rel_path: str
    anchor: str


class SpecService:
    """Loads and mutates the markdown-backed spec tree under repo `specs/`."""

    def __init__(self, workspace: Path | str | None = None, specs_dir: str = "specs") -> None:
        self.workspace = Path(workspace or Path.cwd()).resolve()
        self.spec_root = (self.workspace / specs_dir).resolve()
        if not self.spec_root.exists():
            raise SpecNotFoundError(f"spec root does not exist: {self.spec_root}")
        if not self.spec_root.is_dir():
            raise SpecValidationError(f"spec root is not a directory: {self.spec_root}")

    def get_tree(self) -> list[SpecNode]:
        root_main = self.spec_root / "_main.md"
        if not root_main.exists():
            raise SpecNotFoundError(f"spec root does not contain _main.md: {root_main}")
        visited: set[Path] = set()
        nodes: list[SpecNode] = []
        self._index_file(root_main, depth_base=1, visited=visited, out=nodes)
        return nodes

    def get_node(self, spec_ref: str) -> SpecNodeDetail:
        ref = self._parse_spec_ref(spec_ref)
        file_path = self._resolve_spec_file(ref.rel_path)
        lines = self._read_lines(file_path)
        headings = extract_headings(lines)
        depth = self._depth_for_spec_ref(spec_ref)

        if not headings:
            parsed = extract_document_title_and_description(lines)
            if parsed is None:
                raise SpecNotFoundError(f"no node found for spec_ref: {spec_ref}")
            title, intent, title_line = parsed
            anchor = slugify(title)
            expected_ref = f"{ref.rel_path}#{anchor}"
            if expected_ref != spec_ref:
                raise SpecNotFoundError(f"no node found for spec_ref: {spec_ref}")
            content_lines = lines[title_line + 1 :]
            content = "\n".join(content_lines).strip("\n")
            line_start = title_line + 1
            line_end = len(lines)
            return SpecNodeDetail(
                spec_ref=expected_ref,
                title=title,
                depth=depth,
                file_path=ref.rel_path,
                anchor=anchor,
                intent=intent,
                status=extract_status(lines, title_line + 1, len(lines)),
                content=content,
                line_start=line_start if line_start > 0 else None,
                line_end=line_end if line_end > 0 else None,
            )

        heading_idx = self._find_heading_index(headings, ref.anchor)
        if heading_idx is None:
            raise SpecNotFoundError(f"no node found for spec_ref: {spec_ref}")
        heading = headings[heading_idx]
        end = section_end_index(headings, heading_idx, len(lines), include_children=True)
        intent_end = section_end_index(headings, heading_idx, len(lines), include_children=False)
        intent = extract_intent_text(lines, heading.line_index + 1, intent_end)
        content = "\n".join(lines[heading.line_index + 1 : end]).strip("\n")
        anchor = slugify(heading.title)
        return SpecNodeDetail(
            spec_ref=f"{ref.rel_path}#{anchor}",
            title=heading.title,
            depth=depth,
            file_path=ref.rel_path,
            anchor=anchor,
            intent=intent,
            status=extract_status(lines, heading.line_index + 1, intent_end),
            content=content,
            line_start=heading.line_index + 1,
            line_end=end,
        )

    def update_node(
        self, spec_ref: str, patch: SpecNodePatch | dict[str, object]
    ) -> SpecUpdateResult:
        patch_obj = patch if isinstance(patch, SpecNodePatch) else SpecNodePatch.from_mapping(patch)
        if patch_obj.intent is not UNSET and patch_obj.content is not UNSET:
            raise SpecValidationError("patch cannot set both 'intent' and 'content' together")

        ref = self._parse_spec_ref(spec_ref)
        file_path = self._resolve_spec_file(ref.rel_path)
        lines = self._read_lines(file_path)
        headings = extract_headings(lines)

        if not headings:
            return self._update_plain_document(ref=ref, spec_ref=spec_ref, file_path=file_path, lines=lines, patch=patch_obj)
        return self._update_heading_document(
            ref=ref,
            spec_ref=spec_ref,
            file_path=file_path,
            lines=lines,
            headings=headings,
            patch=patch_obj,
        )

    def _index_file(
        self,
        file_path: Path,
        *,
        depth_base: int,
        visited: set[Path],
        out: list[SpecNode],
    ) -> None:
        canonical = file_path.resolve()
        if canonical in visited:
            return
        visited.add(canonical)

        lines = self._read_lines(canonical)
        headings = extract_headings(lines)
        rel = self._to_rel_path(canonical)

        if not headings:
            parsed = extract_document_title_and_description(lines)
            if parsed is not None:
                title, intent, title_line = parsed
                anchor = slugify(title)
                out.append(
                    SpecNode(
                        spec_ref=f"{rel}#{anchor}",
                        title=title,
                        depth=depth_base,
                        file_path=rel,
                        anchor=anchor,
                        intent=intent,
                        status=extract_status(lines, title_line + 1, len(lines)),
                    )
                )
        else:
            root_level = headings[0].level
            for idx, heading in enumerate(headings):
                # The first heading in a markdown file acts as document title
                # metadata and is intentionally excluded from the tree.
                if idx == 0:
                    continue
                level_delta = heading.level - root_level
                depth = depth_base + max(0, level_delta - 1)
                intent_end = section_end_index(
                    headings, idx, len(lines), include_children=False
                )
                intent = extract_intent_text(lines, heading.line_index + 1, intent_end)
                out.append(
                    SpecNode(
                        spec_ref=f"{rel}#{slugify(heading.title)}",
                        title=heading.title,
                        depth=depth,
                        file_path=rel,
                        anchor=slugify(heading.title),
                        intent=intent,
                        status=extract_status(lines, heading.line_index + 1, intent_end),
                    )
                )

        child_files: list[Path] = []
        seen: set[Path] = set()
        for line in lines:
            parsed_link = parse_markdown_link(line)
            if parsed_link is None:
                continue
            _, target = parsed_link
            target_file = target.split("#", 1)[0].strip()
            if not target_file or not target_file.endswith(".md"):
                continue
            child = (canonical.parent / target_file).resolve()
            if not child.exists() or not child.is_file():
                continue
            if child == canonical or not self._is_within_spec_root(child):
                continue
            if child in seen:
                continue
            seen.add(child)
            child_files.append(child)

        for child in child_files:
            self._index_file(child, depth_base=depth_base + 1, visited=visited, out=out)

    def _depth_for_spec_ref(self, spec_ref: str) -> int:
        for node in self.get_tree():
            if node.spec_ref == spec_ref:
                return node.depth
        raise SpecNotFoundError(f"no node found for spec_ref: {spec_ref}")

    def _update_plain_document(
        self,
        *,
        ref: _SpecRef,
        spec_ref: str,
        file_path: Path,
        lines: list[str],
        patch: SpecNodePatch,
    ) -> SpecUpdateResult:
        parsed = extract_document_title_and_description(lines)
        if parsed is None:
            raise SpecNotFoundError(f"no node found for spec_ref: {spec_ref}")
        title, _, title_line = parsed
        current_ref = f"{ref.rel_path}#{slugify(title)}"
        if current_ref != spec_ref:
            raise SpecNotFoundError(f"no node found for spec_ref: {spec_ref}")

        changed = False
        if patch.title is not UNSET:
            if patch.title is None or not patch.title.strip():
                raise SpecValidationError("title cannot be empty")
            new_title = patch.title.strip()
            if lines[title_line].strip() != new_title:
                lines[title_line] = new_title
                changed = True

        if patch.content is not UNSET:
            replacement = patch.content.splitlines() if patch.content else []
            current_body = lines[title_line + 1 :]
            if current_body != replacement:
                lines = lines[: title_line + 1] + replacement
                changed = True

        if patch.intent is not UNSET:
            intent_idx = find_intent_line(lines, title_line + 1, len(lines))
            if patch.intent is None or not patch.intent.strip():
                if intent_idx is not None:
                    del lines[intent_idx]
                    changed = True
            else:
                new_intent = patch.intent.strip()
                if intent_idx is None:
                    lines.insert(title_line + 1, new_intent)
                    changed = True
                elif lines[intent_idx].strip() != new_intent:
                    lines[intent_idx] = new_intent
                    changed = True

        new_title = lines[title_line].strip()
        new_ref = f"{ref.rel_path}#{slugify(new_title)}"
        if changed:
            self._write_lines(file_path, lines)
        node = self.get_node(new_ref)
        return SpecUpdateResult(
            previous_spec_ref=spec_ref,
            node=node,
            tree_changed=(new_ref != spec_ref),
        )

    def _update_heading_document(
        self,
        *,
        ref: _SpecRef,
        spec_ref: str,
        file_path: Path,
        lines: list[str],
        headings: list[Heading],
        patch: SpecNodePatch,
    ) -> SpecUpdateResult:
        heading_idx = self._find_heading_index(headings, ref.anchor)
        if heading_idx is None:
            raise SpecNotFoundError(f"no node found for spec_ref: {spec_ref}")

        heading = headings[heading_idx]
        current_ref = f"{ref.rel_path}#{slugify(heading.title)}"
        if current_ref != spec_ref:
            raise SpecNotFoundError(f"no node found for spec_ref: {spec_ref}")
        changed = False

        if patch.content is not UNSET:
            end = section_end_index(headings, heading_idx, len(lines), include_children=True)
            has_children = any(
                later.line_index < end and later.level > heading.level
                for later in headings[heading_idx + 1 :]
            )
            if has_children:
                raise SpecValidationError("content updates are only allowed on leaf headings")
            replacement = patch.content.splitlines() if patch.content else []
            current_body = lines[heading.line_index + 1 : end]
            if current_body != replacement:
                lines = (
                    lines[: heading.line_index + 1]
                    + replacement
                    + lines[end:]
                )
                changed = True
            headings = extract_headings(lines)
            heading_idx = self._find_heading_index(headings, ref.anchor)
            if heading_idx is None:
                raise SpecServiceError(
                    f"internal error: cannot re-locate heading for {spec_ref}"
                )
            heading = headings[heading_idx]

        if patch.title is not UNSET:
            if patch.title is None or not patch.title.strip():
                raise SpecValidationError("title cannot be empty")
            new_title = patch.title.strip()
            prefix = "#" * heading.level
            new_heading_line = f"{prefix} {new_title}"
            if lines[heading.line_index].strip() != new_heading_line:
                lines[heading.line_index] = new_heading_line
                changed = True

        if patch.intent is not UNSET:
            intent_end = section_end_index(headings, heading_idx, len(lines), include_children=False)
            intent_idx = find_intent_line(lines, heading.line_index + 1, intent_end)
            if patch.intent is None or not patch.intent.strip():
                if intent_idx is not None:
                    del lines[intent_idx]
                    changed = True
            else:
                new_intent = patch.intent.strip()
                if intent_idx is None:
                    lines.insert(heading.line_index + 1, new_intent)
                    changed = True
                elif lines[intent_idx].strip() != new_intent:
                    lines[intent_idx] = new_intent
                    changed = True

        new_anchor = (
            slugify(patch.title.strip())
            if patch.title is not UNSET and patch.title is not None
            else ref.anchor
        )
        new_ref = f"{ref.rel_path}#{new_anchor}"
        if changed:
            self._write_lines(file_path, lines)
        node = self.get_node(new_ref)
        return SpecUpdateResult(
            previous_spec_ref=spec_ref,
            node=node,
            tree_changed=(new_ref != spec_ref),
        )

    def _parse_spec_ref(self, spec_ref: str) -> _SpecRef:
        rel_path, sep, anchor = spec_ref.partition("#")
        if not sep or not rel_path or not anchor:
            raise SpecValidationError(f"invalid spec_ref: {spec_ref!r}")
        return _SpecRef(rel_path=rel_path, anchor=anchor)

    def _resolve_spec_file(self, rel_path: str) -> Path:
        file_path = (self.workspace / rel_path).resolve()
        if not self._is_within_spec_root(file_path):
            raise SpecValidationError(f"spec_ref path must be under specs/: {rel_path}")
        if not file_path.exists() or not file_path.is_file():
            raise SpecNotFoundError(f"spec file does not exist: {rel_path}")
        return file_path

    def _find_heading_index(self, headings: Iterable[Heading], anchor: str) -> int | None:
        for idx, heading in enumerate(headings):
            if slugify(heading.title) == anchor:
                return idx
        return None

    def _is_within_spec_root(self, path: Path) -> bool:
        try:
            path.relative_to(self.spec_root)
        except ValueError:
            return False
        return True

    def _to_rel_path(self, path: Path) -> str:
        try:
            return path.relative_to(self.workspace).as_posix()
        except ValueError as exc:
            raise SpecValidationError(f"path is outside workspace: {path}") from exc

    def _read_lines(self, path: Path) -> list[str]:
        return path.read_text(encoding="utf-8").splitlines()

    def _write_lines(self, path: Path, lines: list[str]) -> None:
        text = "\n".join(lines)
        if lines:
            text += "\n"
        path.write_text(text, encoding="utf-8")
