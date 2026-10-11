"""Nominal host contract for manager service integrations."""
from __future__ import annotations

from abc import ABC, abstractmethod


class ManagerHostABC(ABC):
    """Base callback contract for manager-hosted services."""

    @abstractmethod
    def update_item_list(self) -> None:
        """Refresh visible list/tree content."""

    @abstractmethod
    def update_button_states(self) -> None:
        """Refresh button enabled/disabled state."""

    @abstractmethod
    def emit_status(self, message: str) -> None:
        """Emit status text for UI presentation."""
