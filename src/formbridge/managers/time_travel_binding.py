"""ObjectState time-travel binding for manager list widgets."""

from __future__ import annotations

import logging
from typing import Any, Optional, TYPE_CHECKING

from objectstate import ObjectStateRegistry

if TYPE_CHECKING:
    from objectstate import ObjectState

logger = logging.getLogger(__name__)


class ManagerTimeTravelBinding:
    """Owns ObjectState registry callbacks and list limbo for a manager widget."""

    def __init__(self, manager: Any, item_access: Any) -> None:
        self._manager = manager
        self._item_access = item_access
        self._limbo_items: dict[str, Any] = {}

    @property
    def in_time_travel(self) -> bool:
        return ObjectStateRegistry.is_restoring_snapshot()

    def connect(self) -> None:
        ObjectStateRegistry.add_unregister_callback(self.on_registry_unregister)
        ObjectStateRegistry.add_register_callback(self.on_registry_register)
        ObjectStateRegistry.add_time_travel_complete_callback(self._manager.on_time_travel_complete)

    def disconnect(self) -> None:
        ObjectStateRegistry.remove_unregister_callback(self.on_registry_unregister)
        ObjectStateRegistry.remove_register_callback(self.on_registry_register)
        ObjectStateRegistry.remove_time_travel_complete_callback(self._manager.on_time_travel_complete)

    def on_registry_unregister(self, scope_key: str, state: "ObjectState") -> None:
        del state
        manager = self._manager
        item = self._find_backing_item_by_scope(manager, scope_key)
        if item is None:
            return

        backing_items = self._item_access.state_binding.items(manager)
        if item in backing_items:
            backing_items.remove(item)
            manager.update_item_list()
            logger.debug("TIME_TRAVEL: Removed item from UI: %s", scope_key)

    def on_registry_register(self, scope_key: str, state: "ObjectState") -> None:
        del state
        if not self.in_time_travel:
            return

        item = self._limbo_items.pop(scope_key, None)
        if item is None:
            return

        manager = self._manager
        backing_items = self._item_access.state_binding.items(manager)
        if item not in backing_items:
            insert_idx = manager.get_item_insert_index(item, scope_key)
            if insert_idx is not None:
                backing_items.insert(insert_idx, item)
            else:
                backing_items.append(item)
            manager.update_item_list()
            logger.debug("TIME_TRAVEL: Added item back to UI: %s", scope_key)

    def refresh_after_time_travel(self, manager: Any) -> None:
        manager.update_item_list()
        manager.update_button_states()

    def _find_backing_item_by_scope(self, manager: Any, scope_key: str) -> Optional[Any]:
        if manager.SCOPE_ITEM_TYPE is None:
            return None

        for index, item in enumerate(self._item_access.state_binding.items(manager)):
            item_scope = self._item_access.list_item_scope_id(item, index)
            if item_scope == scope_key:
                self._limbo_items[scope_key] = item
                return item
        return None
