"""Drag-reorder workflow for manager widgets."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

from objectstate import ObjectStateRegistry


@dataclass(frozen=True)
class ManagerReorderOperations:
    """Nominal operation port consumed by ManagerReorderController."""

    list_widget: Any
    item_from_list_item: Callable[[Any], Any]
    item_id: Callable[[Any], str]
    item_name_singular: str
    item_name_plural: str
    reorder_items: Callable[[int, int], None]
    emit_items_changed: Callable[[], None]
    update_item_list: Callable[[], None]
    emit_status: Callable[[str], None]


class ManagerReorderController:
    """Owns reorder mutation sequencing and user-facing status text."""

    def handle_reordered(
        self,
        operations: ManagerReorderOperations,
        from_index: int,
        to_index: int,
    ) -> None:
        # Qt has already moved the source row when this signal is emitted.
        list_item = operations.list_widget.item(to_index)
        item = operations.item_from_list_item(list_item)
        item_id = operations.item_id(item) if item else "Unknown"

        with ObjectStateRegistry.atomic(f"reorder {operations.item_name_plural}"):
            operations.reorder_items(from_index, to_index)
            operations.emit_items_changed()
            operations.update_item_list()

        direction = "up" if to_index < from_index else "down"
        operations.emit_status(
            f"Moved {operations.item_name_singular} '{item_id}' {direction}"
        )
