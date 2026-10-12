"""Lightweight nominal identities for labelled UI tabs."""

from __future__ import annotations


class TabLabelDeclarationMixin:
    """Nominal tab declaration resolved against a live tab-label projection."""

    label: str

    def index_in(self, labels: tuple[str, ...]) -> int:
        """Resolve this declaration without assuming a fixed tab position."""

        matches = tuple(index for index, label in enumerate(labels) if label == self.label)
        if len(matches) != 1:
            raise ValueError(f"Expected one {self.label!r} tab, found {len(matches)}.")
        return matches[0]
