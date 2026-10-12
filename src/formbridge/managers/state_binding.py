"""Typed state bindings for manager widgets."""

from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True, slots=True)
class ManagerStateBinding:
    """Maps manager-owned list, selection, and signal attributes into base logic."""

    items_attr: str
    selection_attr: str
    selection_signal_attr: str

    def items(self, manager: Any) -> list[Any]:
        return getattr(manager, self.items_attr)

    def set_selection_id(self, manager: Any, item_id: str) -> None:
        setattr(manager, self.selection_attr, item_id)

    def current_selection_id(self, manager: Any) -> str:
        return getattr(manager, self.selection_attr)

    def selection_signal(self, manager: Any) -> Any:
        return getattr(manager, self.selection_signal_attr)
