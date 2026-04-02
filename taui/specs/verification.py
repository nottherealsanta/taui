"""Spec verification — check agent output against spec acceptance criteria.

Each spec node can define a ``verification`` field containing acceptance
criteria (natural language or structured checks).  After an agent
completes work on a spec node, the verifier checks the results against
these criteria.

Verification strategies:
  - **Text match**: simple substring / regex matching in output
  - **File exists**: check that expected files were created
  - **Test command**: run a shell command and check exit code
  - **LLM judge**: ask the LLM to verify (deferred — requires an LLM call)

Usage::

    verifier = SpecVerifier(working_dir=Path("."))
    result = await verifier.verify(spec_node, box)
    if result.passed:
        print("Acceptance criteria met")
"""

from __future__ import annotations

import logging
import re
import subprocess
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)


@dataclass(slots=True)
class VerificationCheck:
    """A single verification check and its result."""

    check_type: str  # "text_match" | "file_exists" | "test_command" | "custom"
    description: str
    passed: bool
    details: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "check_type": self.check_type,
            "description": self.description,
            "passed": self.passed,
            "details": self.details,
        }


@dataclass(slots=True)
class VerificationResult:
    """Aggregate result of all verification checks for a spec node."""

    spec_ref: str
    checks: list[VerificationCheck] = field(default_factory=list)

    @property
    def passed(self) -> bool:
        return all(c.passed for c in self.checks) if self.checks else True

    @property
    def total(self) -> int:
        return len(self.checks)

    @property
    def passed_count(self) -> int:
        return sum(1 for c in self.checks if c.passed)

    def summary(self) -> str:
        if not self.checks:
            return f"{self.spec_ref}: no verification criteria"
        status = "PASS" if self.passed else "FAIL"
        return f"{self.spec_ref}: {status} ({self.passed_count}/{self.total} checks)"

    def to_dict(self) -> dict[str, Any]:
        return {
            "spec_ref": self.spec_ref,
            "passed": self.passed,
            "total": self.total,
            "passed_count": self.passed_count,
            "checks": [c.to_dict() for c in self.checks],
        }


class SpecVerifier:
    """Runs verification checks against spec node acceptance criteria."""

    def __init__(self, working_dir: Path | None = None) -> None:
        self._working_dir = working_dir or Path.cwd()

    async def verify(
        self,
        spec_node: Any,
        output_text: str = "",
        artifacts: list[dict[str, str]] | None = None,
    ) -> VerificationResult:
        """Verify agent output against spec node's acceptance criteria.

        Parses the ``verification`` field of the spec node and runs
        appropriate checks.
        """
        result = VerificationResult(spec_ref=spec_node.spec_ref)

        verification = getattr(spec_node, "verification", None)
        if not verification:
            return result

        # Parse verification directives
        directives = self._parse_directives(verification)

        for directive in directives:
            check = self._run_directive(directive, output_text, artifacts or [])
            result.checks.append(check)

        return result

    def _parse_directives(self, verification: str) -> list[dict[str, str]]:
        """Parse verification text into structured directives.

        Supports formats like:
          - `[file_exists] path/to/file.py`
          - `[test_command] pytest tests/test_auth.py`
          - `[text_match] "expected string"`
          - Plain text (treated as text_match)
        """
        directives: list[dict[str, str]] = []

        for line in verification.strip().splitlines():
            line = line.strip()
            if not line or line.startswith("#"):
                continue

            # Bracketed directive: [type] value
            m = re.match(r"\[(\w+)\]\s*(.*)", line)
            if m:
                directives.append(
                    {
                        "type": m.group(1),
                        "value": m.group(2).strip(),
                    }
                )
            else:
                # Plain text — treat as text match
                directives.append(
                    {
                        "type": "text_match",
                        "value": line,
                    }
                )

        return directives

    def _run_directive(
        self,
        directive: dict[str, str],
        output_text: str,
        artifacts: list[dict[str, str]],
    ) -> VerificationCheck:
        """Run a single verification directive."""
        dtype = directive["type"]
        value = directive["value"]

        if dtype == "file_exists":
            return self._check_file_exists(value)
        elif dtype == "test_command":
            return self._check_test_command(value)
        elif dtype == "text_match":
            return self._check_text_match(value, output_text)
        else:
            return VerificationCheck(
                check_type="custom",
                description=f"[{dtype}] {value}",
                passed=True,  # unknown directives pass by default
                details="Unknown directive type — skipped",
            )

    def _check_file_exists(self, path: str) -> VerificationCheck:
        """Check that a file exists at the given path."""
        full_path = self._working_dir / path
        exists = full_path.exists()
        return VerificationCheck(
            check_type="file_exists",
            description=f"File exists: {path}",
            passed=exists,
            details=str(full_path) if exists else f"Not found: {full_path}",
        )

    def _check_test_command(self, command: str) -> VerificationCheck:
        """Run a shell command and check for zero exit code."""
        try:
            proc = subprocess.run(
                ["sh", "-c", command],
                cwd=self._working_dir,
                capture_output=True,
                text=True,
                timeout=60,
            )
            passed = proc.returncode == 0
            details = proc.stdout.strip() if passed else proc.stderr.strip()
            return VerificationCheck(
                check_type="test_command",
                description=f"Command: {command}",
                passed=passed,
                details=details[:500],
            )
        except subprocess.TimeoutExpired:
            return VerificationCheck(
                check_type="test_command",
                description=f"Command: {command}",
                passed=False,
                details="Command timed out after 60s",
            )
        except Exception as exc:
            return VerificationCheck(
                check_type="test_command",
                description=f"Command: {command}",
                passed=False,
                details=f"Error: {exc}",
            )

    def _check_text_match(self, pattern: str, output_text: str) -> VerificationCheck:
        """Check that the output contains the expected text or matches a regex."""
        # Strip quotes if present
        if pattern.startswith('"') and pattern.endswith('"'):
            pattern = pattern[1:-1]

        # Try exact substring first
        if pattern in output_text:
            return VerificationCheck(
                check_type="text_match",
                description=f"Contains: {pattern[:60]}",
                passed=True,
            )

        # Try regex
        try:
            if re.search(pattern, output_text):
                return VerificationCheck(
                    check_type="text_match",
                    description=f"Matches: {pattern[:60]}",
                    passed=True,
                )
        except re.error:
            pass

        return VerificationCheck(
            check_type="text_match",
            description=f"Contains: {pattern[:60]}",
            passed=False,
            details="Pattern not found in output",
        )
