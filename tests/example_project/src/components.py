"""Shared UI components."""

from dataclasses import dataclass
from typing import Callable, Optional


@dataclass
class Button:
    """Button component."""

    label: str
    variant: str  # primary, secondary, danger
    on_click: Optional[Callable] = None
    disabled: bool = False

    def render(self) -> str:
        """Render button HTML."""
        classes = f"btn btn-{self.variant}"
        if self.disabled:
            classes += " disabled"
        return f'<button class="{classes}">{self.label}</button>'

    def click(self):
        """Handle click event."""
        if self.on_click and not self.disabled:
            self.on_click()


@dataclass
class Input:
    """Input component."""

    name: str
    value: str = ""
    placeholder: str = ""
    max_length: int = 2000
    error: Optional[str] = None

    def render(self) -> str:
        """Render input HTML."""
        classes = "input"
        if self.error:
            classes += " input-error"

        html = f'<input type="text" name="{self.name}" value="{self.value}"'
        html += f' placeholder="{self.placeholder}" maxlength="{self.max_length}"'
        html += f' class="{classes}" />'

        if self.error:
            html += f'<span class="error">{self.error}</span>'

        return html

    def validate(self) -> bool:
        """Validate input value."""
        return len(self.value) <= self.max_length


@dataclass
class Modal:
    """Modal dialog component."""

    title: str
    content: str
    on_confirm: Optional[Callable] = None
    on_cancel: Optional[Callable] = None

    def render(self) -> str:
        """Render modal HTML."""
        return f"""
        <div class="modal-overlay">
            <div class="modal">
                <h2>{self.title}</h2>
                <div class="modal-content">{self.content}</div>
                <div class="modal-actions">
                    <button class="btn btn-secondary" onclick="cancel()">Cancel</button>
                    <button class="btn btn-primary" onclick="confirm()">OK</button>
                </div>
            </div>
        </div>
        """

    def confirm(self):
        """Handle confirm action."""
        if self.on_confirm:
            self.on_confirm()

    def cancel(self):
        """Handle cancel action."""
        if self.on_cancel:
            self.on_cancel()


class ComponentFactory:
    """Factory for creating components."""

    @staticmethod
    def primary_button(label: str, on_click: Callable = None) -> Button:
        """Create a primary button.

        - behavior: High-emphasis action trigger.
        - constraints: Only one primary action per screen.
        """
        return Button(label=label, variant="primary", on_click=on_click)

    @staticmethod
    def secondary_button(label: str, on_click: Callable = None) -> Button:
        """Create a secondary button.

        - behavior: Medium-emphasis action trigger.
        - constraints: Can appear multiple times.
        """
        return Button(label=label, variant="secondary", on_click=on_click)

    @staticmethod
    def danger_button(label: str, on_click: Callable = None) -> Button:
        """Create a danger button.

        - behavior: Delete, remove, or irreversible actions.
        - constraints: Requires confirmation dialog.
        """
        return Button(label=label, variant="danger", on_click=on_click)

    @staticmethod
    def confirm_dialog(
        title: str,
        message: str,
        on_confirm: Callable = None,
        on_cancel: Callable = None,
    ) -> Modal:
        """Create a confirmation dialog.

        - behavior: Focus trap, escape to cancel, enter to confirm.
        - constraints: Must describe action consequences.
        """
        return Modal(
            title=title, content=message, on_confirm=on_confirm, on_cancel=on_cancel
        )
