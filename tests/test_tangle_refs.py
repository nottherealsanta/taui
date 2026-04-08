import pytest

from taui.tangle.refs import extract_tangle_refs


def test_extract_tangle_refs_arrow_and_backtick() -> None:
    lines = [
        "Use -> src/auth.py:register_handler for flow.",
        "Also check `src/db.py:45-52` for writes.",
    ]
    refs = extract_tangle_refs(lines)
    assert len(refs) == 2
    assert refs[0].file_path == "src/auth.py"
    assert refs[0].target == "register_handler"
    assert refs[1].file_path == "src/db.py"
    assert refs[1].target == "45-52"


def test_extract_tangle_refs_unicode_arrow() -> None:
    lines = ["Validate input → src/utils/validation.py:validate_email."]
    refs = extract_tangle_refs(lines)
    assert len(refs) == 1
    assert refs[0].file_path == "src/utils/validation.py"
    assert refs[0].target == "validate_email"


def test_extract_tangle_refs_line_range() -> None:
    lines = ["Hash with argon2id -> src/routes/auth.py:45-52."]
    refs = extract_tangle_refs(lines)
    assert len(refs) == 1
    assert refs[0].target == "45-52"


def test_extract_tangle_refs_multiple_on_same_line() -> None:
    lines = ["See -> src/a.py:foo and `src/b.py:bar`."]
    refs = extract_tangle_refs(lines)
    assert len(refs) == 2
    targets = {r.target for r in refs}
    assert "foo" in targets
    assert "bar" in targets


def test_extract_tangle_refs_empty_lines() -> None:
    refs = extract_tangle_refs([])
    assert refs == []


def test_extract_tangle_refs_no_refs() -> None:
    lines = ["This is plain prose with no code references."]
    refs = extract_tangle_refs(lines)
    assert refs == []


def test_extract_tangle_refs_context_captured() -> None:
    line = "Use -> src/auth.py:login here."
    refs = extract_tangle_refs([line])
    assert len(refs) == 1
    assert "src/auth.py" in refs[0].context


def test_extract_tangle_refs_line_numbers_correct() -> None:
    lines = [
        "No ref here.",
        "Use -> src/foo.py:bar.",
        "Still no ref.",
        "`src/baz.py:qux` mentioned.",
    ]
    refs = extract_tangle_refs(lines)
    assert len(refs) == 2
    assert refs[0].line_in_tangle == 2
    assert refs[1].line_in_tangle == 4


def test_extract_tangle_refs_nested_path() -> None:
    lines = ["See -> src/services/auth/handler.py:process_login."]
    refs = extract_tangle_refs(lines)
    assert len(refs) == 1
    assert refs[0].file_path == "src/services/auth/handler.py"
    assert refs[0].target == "process_login"


def test_extract_tangle_refs_does_not_match_plain_urls() -> None:
    lines = ["Visit https://example.com/foo for docs."]
    refs = extract_tangle_refs(lines)
    # Should not extract refs from URLs — the pattern requires `->` or backtick
    for ref in refs:
        assert "https" not in ref.file_path


def test_extract_tangle_refs_multiple_lines() -> None:
    lines = [
        "First -> src/a.py:func_a.",
        "Second -> src/b.py:func_b.",
        "Third `src/c.py:func_c`.",
    ]
    refs = extract_tangle_refs(lines)
    assert len(refs) == 3
    file_paths = [r.file_path for r in refs]
    assert "src/a.py" in file_paths
    assert "src/b.py" in file_paths
    assert "src/c.py" in file_paths
