"""
Discriminated union types for parameter information.

This module implements React-style discriminated unions for type-safe parameter handling.
Instead of using boolean flags (is_optional, is_nested), we use polymorphic types that
are automatically selected based on type annotations.

Key features:
1. Metaclass auto-registration - all ParameterInfo subclasses auto-register
2. Type-driven factory - create_parameter_info() uses type introspection
3. Zero boilerplate - just define new dataclass with matches() predicate
4. Type-safe dispatch - services use class name for automatic dispatch

Pattern (React-style):
    Instead of:
        @dataclass
        class ParameterInfo:
            is_optional: bool
            is_nested: bool

        if info.is_optional and info.is_nested:
            # handle optional dataclass

    Use:
        @dataclass
        class OptionalDataclassInfo(metaclass=ParameterInfoMeta):
            @staticmethod
            def matches(param_type): ...

        if isinstance(info, OptionalDataclassInfo):
            # Type checker knows info is OptionalDataclassInfo!

Architecture:
    - ParameterInfoMeta: Metaclass that auto-registers all subclasses
    - ParameterInfoBase: Base class for all parameter info types
    - OptionalDataclassInfo: Optional[Dataclass] parameters (checkbox-controlled)
    - DirectDataclassInfo: Direct Dataclass parameters (always exists)
    - GenericInfo: Generic parameters (simple widgets)
    - create_parameter_info(): Factory that auto-selects correct type
"""

import logging
from abc import ABC, ABCMeta
from collections.abc import Callable
from dataclasses import dataclass, is_dataclass

from objectstate.lazy_factory import get_base_type_for_lazy
from python_introspect import optional_member_type, resolve_annotated

from formbridge.forms.parameter_value_contracts import ParameterValue

logger = logging.getLogger(__name__)


InlineDataclassWidgetFactory = Callable


class _InlineDataclassWidgetCatalog:
    """Private registry authority for dataclasses with structural inline editors."""

    _factories: dict[type, InlineDataclassWidgetFactory] = {}

    @classmethod
    def register(
        cls,
        dataclass_type: type,
        widget_factory: InlineDataclassWidgetFactory,
    ) -> None:
        if not is_dataclass(dataclass_type):
            raise TypeError(
                "Inline dataclass widgets can only be registered for dataclass types; "
                f"got {dataclass_type!r}."
            )
        registered = cls._factories.get(dataclass_type)
        if registered is not None and registered is not widget_factory:
            raise ValueError(
                f"{dataclass_type.__qualname__} already has an inline widget factory "
                f"({registered!r}); it cannot also use {widget_factory!r}."
            )
        cls._factories[dataclass_type] = widget_factory

    @classmethod
    def factory_for(cls, dataclass_type: type) -> InlineDataclassWidgetFactory | None:
        for candidate_type in cls._candidate_types(dataclass_type):
            factory = cls._factories.get(candidate_type)
            if factory is not None:
                return factory
        return None

    @classmethod
    def has_factory_for(cls, dataclass_type: type) -> bool:
        return cls.factory_for(dataclass_type) is not None

    @classmethod
    def _candidate_types(cls, dataclass_type: type) -> tuple[type, ...]:
        """Return exact, lazy-base, and inherited dataclass types for lookup."""

        base_type = get_base_type_for_lazy(dataclass_type)
        root_types = (
            (dataclass_type,)
            if base_type is None or base_type is dataclass_type
            else (dataclass_type, base_type)
        )
        candidates: list[type] = []
        seen: set[type] = set()
        for root_type in root_types:
            for candidate_type in root_type.__mro__:
                if candidate_type is object or candidate_type in seen:
                    continue
                candidates.append(candidate_type)
                seen.add(candidate_type)
        return tuple(candidates)


def register_inline_dataclass_widget(
    dataclass_type: type,
    widget_factory: InlineDataclassWidgetFactory,
) -> None:
    """Register a full-row editor for a dataclass type before nested fallback."""
    _InlineDataclassWidgetCatalog.register(dataclass_type, widget_factory)


@dataclass
class ParameterInfoBase(ABC):
    """ABC for parameter information objects - enforces explicit interface."""

    name: str
    type: type
    current_value: ParameterValue | None
    description: str | None = None

    # Widget creation type - subclasses override. Imported lazily to avoid circular imports.
    widget_creation_type: str = "REGULAR"  # Default, overridden by subclasses


class ParameterInfoMeta(ABCMeta):
    """
    Metaclass for auto-registration of ParameterInfo types.

    All classes with a matches() method are automatically registered
    in the global registry for use by the factory function.

    This eliminates manual registration and enables zero-boilerplate
    addition of new parameter types.
    """

    _registry: list[type] = []

    def __new__(mcs, name, bases, namespace):
        cls = super().__new__(mcs, name, bases, namespace)

        # Auto-register if it has a matches() predicate
        if "matches" in namespace and callable(namespace["matches"]):
            mcs._registry.append(cls)
            logger.debug(f"Auto-registered ParameterInfo type: {name}")

        return cls

    @classmethod
    def get_registry(cls) -> list[type]:
        """Get all registered ParameterInfo types."""
        return cls._registry.copy()


@dataclass
class OptionalDataclassInfo(ParameterInfoBase, metaclass=ParameterInfoMeta):
    """
    Parameter info for Optional[Dataclass] types.

    These parameters:
    - Have a checkbox to enable/disable
    - Have a nested form that appears when enabled
    - Can be None when checkbox is unchecked
    - Support lazy inheritance from parent configs

    Examples:
        def process(config: Optional[ProcessingConfig]): ...
        def analyze(settings: Optional[AnalysisSettings]): ...
    """

    default_value: ParameterValue | None = None
    is_required: bool = True
    widget_creation_type: str = "OPTIONAL_NESTED"

    @staticmethod
    def matches(param_type: type) -> bool:
        """
        Predicate: Does this type annotation match Optional[Dataclass]?

        Returns True if:
        - Type is Union[T, None] (i.e., Optional[T])
        - T is a dataclass
        """
        inner_type = optional_member_type(param_type)
        return inner_type is not None and is_dataclass(inner_type)


@dataclass
class InlineDataclassWidgetInfo(ParameterInfoBase, metaclass=ParameterInfoMeta):
    """
    Parameter info for dataclasses with a registered structural inline editor.

    These parameters:
    - Are still regular dataclass-backed values
    - Use a registered widget instead of the default nested field form
    - Fall back to DirectDataclassInfo when no inline widget is registered
    """

    default_value: ParameterValue | None = None
    is_required: bool = True
    widget_creation_type: str = "INLINE_DATACLASS"

    @staticmethod
    def matches(param_type: type) -> bool:
        return is_dataclass(param_type) and _InlineDataclassWidgetCatalog.has_factory_for(
            param_type
        )

    def widget_factory(self) -> InlineDataclassWidgetFactory:
        factory = _InlineDataclassWidgetCatalog.factory_for(self.type)
        if factory is None:
            raise ValueError(
                "No inline dataclass widget registered for "
                f"{self.type!r}; DirectDataclassInfo should have handled it."
            )
        return factory


@dataclass
class DirectDataclassInfo(ParameterInfoBase, metaclass=ParameterInfoMeta):
    """
    Parameter info for direct Dataclass types (non-optional).

    These parameters:
    - Always exist (never None)
    - Have a nested form that's always visible
    - Preserve object identity during reset
    - Don't have a checkbox

    Examples:
        def process(config: ProcessingConfig): ...
        def analyze(settings: AnalysisSettings): ...
    """

    default_value: ParameterValue | None = None
    is_required: bool = True
    widget_creation_type: str = "NESTED"

    @staticmethod
    def matches(param_type: type) -> bool:
        """
        Predicate: Does this type annotation match a direct Dataclass?

        Returns True if:
        - Type is a dataclass
        - Type is NOT Optional
        """
        return is_dataclass(param_type)


@dataclass
class GenericInfo(ParameterInfoBase, metaclass=ParameterInfoMeta):
    """
    Parameter info for generic types (int, str, Path, etc.).

    These parameters:
    - Use simple widgets (QLineEdit, QSpinBox, etc.)
    - Don't have nested forms
    - Support lazy inheritance via placeholders
    - Are the most common parameter type

    Examples:
        def process(threshold: int): ...
        def analyze(input_path: Path): ...
        def filter(sigma: float): ...
    """

    default_value: ParameterValue | None = None
    is_required: bool = True

    @staticmethod
    def matches(param_type: type) -> bool:
        """
        Predicate: Fallback - matches everything.

        This should be registered LAST in the registry so it acts
        as a catch-all for any types not matched by other predicates.
        """
        return True


# Union type for type hints (React-style)
ParameterInfo = (
    OptionalDataclassInfo | InlineDataclassWidgetInfo | DirectDataclassInfo | GenericInfo
)


def create_parameter_info(
    name: str,
    param_type: type,
    current_value: ParameterValue | None,
    default_value: ParameterValue | None = None,
    description: str | None = None,
    is_required: bool = True,
) -> ParameterInfo:
    """
    Factory function that auto-selects the correct ParameterInfo subclass.

    Uses type introspection to determine which ParameterInfo type to create.
    This eliminates manual if-elif-else chains and enables type-safe dispatch.

    Args:
        name: Parameter name
        param_type: Parameter type annotation
        current_value: Current parameter value
        default_value: Default parameter value
        description: Parameter description
        is_required: Whether parameter is required

    Returns:
        Correct ParameterInfo subclass instance

    Raises:
        ValueError: If no matching ParameterInfo type found

    Examples:
        >>> from typing import Optional
        >>> @dataclass
        ... class Config: pass

        >>> info1 = create_parameter_info('config', Optional[Config], None)
        >>> type(info1).__name__
        'OptionalDataclassInfo'

        >>> info2 = create_parameter_info('config', Config, Config())
        >>> type(info2).__name__
        'DirectDataclassInfo'

        >>> info3 = create_parameter_info('value', int, 42)
        >>> type(info3).__name__
        'GenericInfo'
    """
    # Match structural identity once; the admitted declaration keeps its metadata.
    structural_type = resolve_annotated(param_type)
    for info_class in ParameterInfoMeta.get_registry():
        if info_class.matches(structural_type):
            return info_class(
                name=name,
                type=param_type,
                current_value=current_value,
                default_value=default_value,
                description=description,
                is_required=is_required,
            )

    # Should never reach here due to GenericInfo fallback
    raise ValueError(
        f"No matching ParameterInfo type for {param_type}. "
        f"This should never happen - GenericInfo should match everything."
    )
