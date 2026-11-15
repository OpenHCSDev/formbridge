"""Shared field editing, selection and construction for every UI backend.

A backend's editor family inherits these parents and supplies native controls,
feedback display and painting. The bodies here are moved from Toad's
``toad.forms.editors`` and owned once; no backend restates them.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from collections.abc import Iterable
from enum import Enum
from typing import ClassVar, Self

from formbridge.forms.declared_fields import (
    DeclaredField,
    DeclaredViews,
    Multiline,
    OptionalMemberField,
    declarations,
)
from formbridge.forms.ui_utils import format_enum_display
from python_introspect import AnnotationChoices, declared_annotation_choices, resolve_annotated
from python_introspect.validation import validate_annotation_value


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
    """Shared line-editor behavior: read text as the field's type, validate before send.

    Native finish decides when to commit (on blur, enter, etc.) and uses
    read/acceptable from here. The native text accessor stays native.
    """

    def read(self, text: str) -> object:
        """Parse text into the field's value. Default: identity (strings)."""
        return text

    def acceptable(self, text: str) -> bool:
        """Whether the text would be a valid edit. Used by native validators."""
        try:
            validate_annotation_value(
                self.field.annotation, self.read(text), path=self.field.label
            )
        except (TypeError, ValueError):
            return False
        return True


class SelectEditing(ValueEditing):
    """Shared select behavior: option list, value-in-list check, label lookup."""

    @abstractmethod
    def options(self) -> Iterable[tuple[str, object]]:
        """Each offered value with its display label."""

    @abstractmethod
    def displayed_options(self) -> Iterable[tuple[str, object]]:
        """The currently installed native options. Native selects read this."""

    def lists(self, value: object) -> bool:
        """Whether the current option list contains this value."""
        return any(value == choice for _, choice in self.displayed_options())

    def value_text(self, value: object) -> str:
        for label, choice in self.displayed_options():
            if value == choice:
                return label
        return super().value_text(value)


class ChoicesEditing(SelectEditing):
    """Shared choices behavior: read AnnotationChoices from the field's annotation."""

    @property
    def choices(self) -> AnnotationChoices:
        choices = declared_annotation_choices(self.field.annotation)
        assert choices is not None
        return choices

    def options(self) -> Iterable[tuple[str, object]]:
        return self.choices.labelled_choices()


class EnumEditing(SelectEditing):
    """Shared enum behavior: iterate enum members as labelled options."""

    def options(self) -> Iterable[tuple[str, object]]:
        members: type[Enum] = resolve_annotated(self.field.annotation)  # type: ignore[assignment]
        return ((format_enum_display(member), member) for member in members)


class MultilineEditing(ValueEditing):
    """Shared multiline behavior: suppress default note (too long for help text)."""

    def default_note(self) -> str:
        return ""


class OptionalEditing(ValueEditing):
    """Shared optional behavior: held/member state, toggle, finish delegation.

    Native controls create the checkbox and member editor. The shared
    algorithm owns the held-value semantics: unchecking sends None,
    checking restores the member editor, finish delegates to the member.
    """

    @property
    @abstractmethod
    def member_editor(self) -> ValueEditing:
        """The member editor, created by native bind_control."""

    @abstractmethod
    def set_member_shown(self, held: bool) -> None:
        """Show or hide the member editor natively."""

    @abstractmethod
    def paint_held(self, held: bool) -> None:
        """Update the native checkbox without triggering a change echo."""

    def change_held(self, held: bool) -> None:
        """Called by native checkbox change. The shared algorithm."""
        self.set_member_shown(held)
        if not held:
            self.clear_feedback()
            self.send(None)

    def finish(self) -> None:
        self.member_editor.finish()

    def value_text(self, value: object) -> str:
        return "not set" if value is None else self.member_editor.value_text(value)
