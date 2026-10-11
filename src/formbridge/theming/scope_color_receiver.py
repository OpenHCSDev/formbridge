"""Nominal contract for widgets that receive scope color schemes."""

from __future__ import annotations

from abc import ABC, abstractmethod


class ScopeColorSchemeReceiver(ABC):
    """Nominal receiver for scope color propagation."""

    @abstractmethod
    def set_scope_color_scheme(self, scheme) -> None:
        """Apply or clear a scope color scheme."""
