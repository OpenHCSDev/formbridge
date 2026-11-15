"""Shared field editing, selection and construction for every UI backend.

A backend's editor family inherits these parents and supplies native controls,
feedback display and painting. The bodies here are moved from Toad's
``toad.forms.editors`` and owned once; no backend restates them.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import ClassVar, Self

from formbridge.forms.declared_fields import (
    DeclaredField,
    DeclaredViews,
    OptionalMemberField,
    declarations,
)


class ValueEditing(DeclaredViews):
    """Shared editing behavior: selection, value text, send/refuse and finish.

    A native editor composes this with its widget base. The bound field lives
    here; native feedback display is abstract so the original send/refuse bodies
    move unchanged.
    """

    field: DeclaredField

    @classmethod
    def declared_for(cls, field: DeclaredField) -> Self:
        """Select the editor for this field's annotation through the DeclaredViews family."""
        return cls.showing(declarations(field.annotation))(field)

    def value_text(self, value: object) -> str:
        return self.field.placeholder if value is None else str(value)

    def default_note(self) -> str:
        return f"\ndefault: {self.value_text(self.field.default)}" if self.field.has_default else ""

    def send(self, value: object) -> None:
        try:
            self.field.edit(value)
        except (TypeError, ValueError) as error:
            self.refuse(error)
        else:
            self.clear_feedback()

    def refuse(self, error: Exception) -> None:
        self.display_feedback(str(error))

    def finish(self) -> None:
        pass

    @abstractmethod
    def display_feedback(self, text: str) -> None:
        """Show validation feedback on the native control."""

    @abstractmethod
    def clear_feedback(self) -> None:
        """Clear feedback silently. OptionalEditor uses this when hiding
        the member, so an old member notification cannot overwrite a newer
        parent refusal."""


class ControlConstruction(ValueEditing):
    """Field-only constructor: bind the field, compute control arguments, init the
    native control through the MRO, then bind native events.

    A native editor puts this before its widget base so the field is bound
    before the native constructor runs.
    """

    def __init__(self, field: DeclaredField) -> None:
        self.field = field
        super().__init__(**self.control_arguments())
        self.bind_control()

    def control_arguments(self) -> dict[str, object]:
        return {}

    @abstractmethod
    def bind_control(self) -> None:
        """Connect native control events after initialization."""


class LineEditing(ValueEditing):
    """Shared line-editor behavior: read, acceptable, finish."""

    @abstractmethod
    def read_text(self) -> str:
        """The current native text."""

    def acceptable(self, text: str) -> bool:
        try:
            self.field.validate(self.read(text))
            return True
        except (TypeError, ValueError):
            return False

    def read(self, text: str) -> object:
        return text

    def finish(self) -> None:
        text = self.read_text()
        try:
            value = self.read(text)
            self.field.validate(value)
        except (TypeError, ValueError) as error:
            self.refuse(error)
            self.restore_value()
        else:
            self.send(value)

    @abstractmethod
    def restore_value(self) -> None:
        """Paint the committed value back after a refused edit."""
