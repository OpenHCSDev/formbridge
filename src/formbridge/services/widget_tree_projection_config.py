"""Lightweight widget-tree projection policy shared by window managers."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import MISSING, dataclass, field
from objectstate.declarations import admit_root_value
from typing import Any, TypeAlias

DEFAULT_MAXIMUM_WIDGET_TEXT_LENGTH = 4096
DEFAULT_MAXIMUM_ITEM_MODEL_NODES = 512
DEFAULT_TEXT_TRUNCATION_SUFFIX = "...<truncated>"
WidgetPath: TypeAlias = tuple[int, ...]
CompactFieldPredicate: TypeAlias = Callable[[object, object], bool]


@dataclass(frozen=True, slots=True)
class CompactFieldProjection:
    """Declaration-owned rules for one field in a compact dataclass projection."""

    includes: CompactFieldPredicate


def always_project_compact_field(_owner: object, _value: object) -> bool:
    """Retain a field even when its current value is otherwise empty."""

    return True


def _compact_value_carries_information(value: object) -> bool:
    if value is None:
        return False
    if isinstance(value, bool):
        return value
    if isinstance(value, (str, bytes, tuple, list, dict, set, frozenset)):
        return bool(value)
    return True


def compact_dataclass_projection(value: object) -> dict[str, Any]:
    """Project one dataclass through its field-owned compactness declarations."""

    projected: dict[str, Any] = {}
    node = admit_root_value(value)
    for declared_field, member in node.projection_fields():
        field_value = member.stored
        required = declared_field.default is MISSING and declared_field.default_factory is MISSING
        if CompactFieldProjection in declared_field.metadata:
            policy = declared_field.metadata[CompactFieldProjection]
            if not isinstance(policy, CompactFieldProjection):
                raise TypeError(
                    f"{type(value).__name__}.{declared_field.name} declares an invalid "
                    "compact field projection."
                )
            includes = required or policy.includes(value, field_value)
        else:
            # Empty values may only disappear when the declaration restores
            # that exact value. Do not evaluate factories during serialization.
            includes = required or _compact_value_carries_information(field_value) or not (
                declared_field.default is not MISSING
                and type(field_value) is type(declared_field.default)
                and member.source_equals(node.declaration.field_types[declared_field.name].admit(declared_field.default))
            )
        if includes:
            projected[declared_field.name] = field_value
    return projected


@dataclass(frozen=True, slots=True)
class WidgetTextProjection:
    """Bounded text projection with explicit truncation state."""

    value: str
    truncated: bool


@dataclass(frozen=True, slots=True)
class WidgetNodeIdentity:
    """Stable widget identity fields shared by projector and transport DTOs."""

    path: WidgetPath = field(
        metadata={
            CompactFieldProjection: CompactFieldProjection(
                includes=always_project_compact_field
            )
        }
    )
    path_id: str = field(
        metadata={
            CompactFieldProjection: CompactFieldProjection(
                includes=always_project_compact_field
            )
        }
    )
    child_index: int | None = field(
        metadata={
            CompactFieldProjection: CompactFieldProjection(
                includes=always_project_compact_field
            )
        }
    )
    class_name: str = field(
        metadata={
            CompactFieldProjection: CompactFieldProjection(
                includes=always_project_compact_field
            )
        }
    )
    object_name: str
    accessible_name: str
    accessible_description: str


@dataclass(frozen=True, kw_only=True)
class WidgetTreeProjectionControls:
    """Projection controls that do not require importing Qt widget classes."""

    maximum_text_length: int = DEFAULT_MAXIMUM_WIDGET_TEXT_LENGTH
    maximum_item_model_nodes: int | None = DEFAULT_MAXIMUM_ITEM_MODEL_NODES
    truncation_suffix: str = DEFAULT_TEXT_TRUNCATION_SUFFIX

    @classmethod
    def default_maximum_text_length(cls) -> int:
        return DEFAULT_MAXIMUM_WIDGET_TEXT_LENGTH

    @classmethod
    def default_maximum_item_model_nodes(cls) -> int:
        return DEFAULT_MAXIMUM_ITEM_MODEL_NODES

    @classmethod
    def default_truncation_suffix(cls) -> str:
        return DEFAULT_TEXT_TRUNCATION_SUFFIX

    def __post_init__(self) -> None:
        if self.maximum_text_length < len(self.truncation_suffix):
            raise ValueError("maximum_text_length must be at least the truncation suffix length")
        if self.maximum_item_model_nodes is not None and self.maximum_item_model_nodes < 0:
            raise ValueError("maximum_item_model_nodes must be non-negative or None")

    def project_text(self, text: str) -> WidgetTextProjection:
        if len(text) <= self.maximum_text_length:
            return WidgetTextProjection(value=text, truncated=False)

        prefix_length = self.maximum_text_length - len(self.truncation_suffix)
        return WidgetTextProjection(
            value=f"{text[:prefix_length]}{self.truncation_suffix}",
            truncated=True,
        )

    def as_projection_policy(
        self,
        *,
        maximum_depth: int | None = None,
        maximum_nodes: int | None = None,
    ) -> WidgetTreeProjectionPolicy:
        return WidgetTreeProjectionPolicy(
            maximum_text_length=self.maximum_text_length,
            maximum_item_model_nodes=self.maximum_item_model_nodes,
            truncation_suffix=self.truncation_suffix,
            maximum_depth=maximum_depth,
            maximum_nodes=maximum_nodes,
        )


@dataclass(frozen=True, slots=True, kw_only=True)
class WidgetTreeProjectionPolicy(WidgetTreeProjectionControls):
    """Concrete projection policy used by Qt widget tree projectors."""

    maximum_depth: int | None = None
    maximum_nodes: int | None = None

    def __post_init__(self) -> None:
        WidgetTreeProjectionControls.__post_init__(self)
        if self.maximum_depth is not None and self.maximum_depth < 0:
            raise ValueError("maximum_depth must be non-negative or None")
        if self.maximum_nodes is not None and self.maximum_nodes < 1:
            raise ValueError("maximum_nodes must be positive or None")


DEFAULT_WIDGET_TREE_PROJECTION_POLICY = WidgetTreeProjectionPolicy()
