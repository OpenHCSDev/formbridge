"""Typed list-item hook declarations for manager widgets."""

from __future__ import annotations

from abc import ABC, abstractmethod
from collections.abc import Callable, Mapping
from dataclasses import dataclass, field
from operator import attrgetter
from typing import Any


class ItemIdProjection(ABC):
    """Projects a stable selection id from a manager backing item."""

    @abstractmethod
    def __call__(self, item: Any) -> str:
        ...


@dataclass(frozen=True, slots=True)
class DictItemIdProjection(ItemIdProjection):
    """Project an item id from a mapping key."""

    key: str

    def __call__(self, item: Any) -> str:
        if not isinstance(item, Mapping):
            raise TypeError(
                f"Dict item-id projection expects Mapping, got {type(item).__name__}."
            )
        return str(item[self.key])


@dataclass(frozen=True, slots=True)
class AttributeItemIdProjection(ItemIdProjection):
    """Project an item id from an object attribute path."""

    path: str
    _getter: Callable[[Any], Any] = field(init=False, repr=False)

    def __post_init__(self) -> None:
        object.__setattr__(self, "_getter", attrgetter(self.path))

    def __call__(self, item: Any) -> str:
        return str(self._getter(item))


@dataclass(frozen=True, slots=True)
class ManagerItemHooks:
    """Typed source for list-item behavior consumed by AbstractManagerWidget."""

    id_projection: ItemIdProjection = field(
        default_factory=lambda: AttributeItemIdProjection("id")
    )
    preserve_selection_pred: Callable[[Any], bool] = lambda _manager: False

    def item_id(self, item: Any) -> str:
        return self.id_projection(item)

    def should_preserve_selection(self, manager: Any) -> bool:
        return bool(self.preserve_selection_pred(manager))

    def list_item_data_for(self, item: Any, index: int) -> Any:
        """Return the stable, transport-safe identity stored in ``UserRole``."""

        del index
        return self.item_id(item)

    def item_from_list_data(self, data: Any, items: list[Any]) -> Any:
        """Resolve one stable row identity against the authoritative backing list."""

        if data is None:
            return None
        item_id = str(data)
        return next(
            (item for item in items if self.item_id(item) == item_id),
            None,
        )
