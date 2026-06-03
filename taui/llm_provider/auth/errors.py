"""Shared provider-authentication errors."""

from __future__ import annotations


class ProviderAuthRequired(RuntimeError):
    """A provider needs authentication, but interactive login is not allowed here.

    Raised when a session is created for a provider that has no usable saved
    credentials. Unlike the interactive device-flow login, this never blocks on
    user input — the caller (e.g. the TUI) surfaces it so the user can run
    ``taui --login`` from a real terminal.
    """

    def __init__(self, provider: str, message: str | None = None) -> None:
        self.provider = provider
        super().__init__(
            message or f"No saved credentials for {provider!r}. Run `taui --login`."
        )
