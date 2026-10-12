"""Generic preview formatting helpers."""

from collections.abc import Callable, Collection, Mapping, MutableSequence, Sequence, Set
from dataclasses import dataclass
from enum import Enum, StrEnum
from functools import singledispatch
from types import FunctionType, MethodType
from typing import cast

from objectstate import ParameterOwner


@dataclass(frozen=True, slots=True)
class PreviewLabelResolution:
    """Preview label together with the config declaration that owns it."""

    owner: type
    label: str


@dataclass(frozen=True, slots=True)
class PreviewFieldAbbreviationResolution:
    """Field abbreviation together with the declaration that owns it."""

    owner: type
    abbreviation: str


def canonical_declaration_mro(declaration_type: type) -> tuple[type, ...]:
    """Return the semantic declaration MRO, excluding generated lazy wrappers."""
    from objectstate.lazy_factory import get_base_type_for_lazy

    canonical_type = get_base_type_for_lazy(declaration_type) or declaration_type
    return canonical_type.__mro__


def resolve_preview_label(config: object) -> PreviewLabelResolution | None:
    """Resolve preview metadata from the canonical config declaration MRO."""
    from objectstate.lazy_factory import PREVIEW_LABEL_REGISTRY

    for candidate in canonical_declaration_mro(type(config)):
        label = PREVIEW_LABEL_REGISTRY.get(candidate)
        if label is not None:
            return PreviewLabelResolution(owner=candidate, label=label)
    return None


def resolve_field_abbreviation(
    declaration: ParameterOwner,
    field_name: str,
) -> PreviewFieldAbbreviationResolution | None:
    """Resolve a field abbreviation only from its canonical declaration MRO."""
    from objectstate.lazy_factory import FIELD_ABBREVIATIONS_REGISTRY

    if not isinstance(declaration, type):
        return None

    for candidate in canonical_declaration_mro(declaration):
        abbreviation = FIELD_ABBREVIATIONS_REGISTRY.get(candidate, {}).get(field_name)
        if abbreviation is not None:
            return PreviewFieldAbbreviationResolution(
                owner=candidate,
                abbreviation=abbreviation,
            )
    return None


def check_enabled_field(config: object) -> bool:
    """Return the nominal ``Enableable`` state of a config declaration."""
    from python_introspect import Enableable

    if not issubclass(type(config), Enableable):
        return True
    return cast(Enableable, config).enabled


class PreviewValueDetail(StrEnum):
    """Collection display modes carry their own leaf formatting behavior."""

    COMPACT = ("compact", lambda values: f"[{len(values)}]")
    EXPANDED = ("expanded", repr)

    def __new__(cls, value: str, formatter: Callable[[Collection], str]):
        member = str.__new__(cls, value)
        member._value_ = value
        member._formatter = formatter
        return member

    def format_collection(self, value: Collection) -> str:
        return self._formatter(value)


@singledispatch
def format_preview_value(
    value: object, detail: PreviewValueDetail = PreviewValueDetail.COMPACT
) -> str | None:
    """Project display values by nominal type, without knowing config field names."""
    if callable(value) and not isinstance(value, type):
        return type(value).__name__
    return str(value)


@format_preview_value.register(type(None))
def _format_absent(value, detail=PreviewValueDetail.COMPACT) -> None:
    return None


@format_preview_value.register(Enum)
def _format_enum(value: Enum, detail=PreviewValueDetail.COMPACT) -> str | None:
    return value.name if value.value is not None else None


@format_preview_value.register(FunctionType)
@format_preview_value.register(MethodType)
def _format_function(value, detail=PreviewValueDetail.COMPACT) -> str:
    return value.__name__


@format_preview_value.register(Mapping)
@format_preview_value.register(Set)
def _format_collection(value: Collection, detail=PreviewValueDetail.COMPACT) -> str | None:
    return detail.format_collection(value) if value else None


@format_preview_value.register(MutableSequence)
@format_preview_value.register(tuple)
def _format_sequence(value: Sequence, detail=PreviewValueDetail.COMPACT) -> str | None:
    if value and all(isinstance(element, Enum) for element in value):
        return ",".join(str(element.value) for element in value)
    return _format_collection(value, detail)


@dataclass(frozen=True, slots=True)
class PreviewFieldFormatRequest:
    """One resolved value together with its ObjectState-recorded declaration.

    Standalone requests use the generic value formatter; a configured preview
    service supplies its declaration-owned display policy.
    """

    field_path: str
    value: object
    field_owner: ParameterOwner
    value_formatter: Callable[[object], str | None] = format_preview_value

    @property
    def field_name(self) -> str:
        """Return the leaf field name declared by ``field_owner``."""
        return self.field_path.rsplit(".", 1)[-1]
