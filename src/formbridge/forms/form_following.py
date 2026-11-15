"""Shared form-following behavior: subscribe to ObjectState, repaint values, mark dirty.

A native form view inherits FollowingForm and supplies the native mounting,
painting and field-view index. The subscription algorithms here are the original
bodies from Toad's FormView, moved once.
"""

from __future__ import annotations

from collections.abc import Iterator, Mapping, Sequence
from typing import Any

from objectstate import ObjectState

from formbridge.forms.value_editing import ValueEditing


class FollowedFieldView:
    """A part of a form that holds nested field views and supports filtering."""

    def values(self) -> Iterator[FollowedValueView]:
        raise NotImplementedError

    def filter(self, term: str) -> bool:
        raise NotImplementedError


class FollowedValueView(FollowedFieldView):
    """One field's view: the editor, its field and its mark."""

    field: Any
    editor: ValueEditing

    def mark(self, changed: bool) -> None:
        raise NotImplementedError

    def values(self) -> Iterator[FollowedValueView]:
        yield self

    def filter(self, term: str) -> bool:
        return term in self.field.search_text


class FollowingForm:
    """Shared subscription to ObjectState: repaint changed values, mark dirty fields.

    A native form composes this with its container widget. The subscription
    attaches once, detaches before the native view disappears, and late callbacks
    cannot act on a replacement view. Change work is proportional to affected
    visible paths, not a full rebuild.
    """

    state: ObjectState
    parts: Sequence[FollowedFieldView]

    def build_index(self) -> None:
        """Build the path-to-view index once from parts. Call after parts are
        populated; late-built views register through their native build owner."""
        self.values: Mapping[str, FollowedValueView] = {
            view.field.path.value: view
            for part in self.parts
            for view in part.values()
        }

    def follow_state(self) -> None:
        self.state.on_resolved_changed(self.values_changed)
        self.state.on_state_changed(self.marks_changed)
        self.marks_changed(self.state.dirty_fields)

    def leave_state(self) -> None:
        self.state.off_resolved_changed(self.values_changed)
        self.state.off_state_changed(self.marks_changed)

    def values_changed(self, paths: set[str]) -> None:
        for path in paths & self.values.keys():
            self.repaint_editor(self.values[path].editor)

    def marks_changed(self, paths: set[str]) -> None:
        differ = self.state.dirty_fields
        for path in paths & self.values.keys():
            self.values[path].mark(path in differ)

    def finish(self) -> None:
        for view in self.values.values():
            view.editor.finish()

    def filter_parts(self, term: str) -> None:
        for part in self.parts:
            part.filter(term.lower())

    def repaint_editor(self, editor: ValueEditing) -> None:
        """Repaint one editor from its field's current value. Native: check
        the editor is still mounted/live before painting."""
        raise NotImplementedError
