"""Parameter declarations select their most specific kind through inheritance.

The root is an ordinary value. Nullable and dataclass declarations compose;
inline factories specialize dataclasses without changing their value identity.
"""

from abc import ABCMeta
from collections.abc import Callable
from dataclasses import dataclass, is_dataclass

from objectstate.lazy_factory import get_base_type_for_lazy
from python_introspect import optional_member_type, resolve_annotated

from formbridge.forms.parameter_value_contracts import ParameterValue


InlineDataclassWidgetFactory = Callable


class _InlineDataclassWidgetCatalog:
    """Factories for structural inline editors, not a second kind registry."""

    _factories: dict[type, InlineDataclassWidgetFactory] = {}

    @classmethod
    def register(cls, dataclass_type: type, widget_factory: InlineDataclassWidgetFactory) -> None:
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
        base_type = get_base_type_for_lazy(dataclass_type)
        root_types = ((dataclass_type,) if base_type is None or base_type is dataclass_type
                      else (dataclass_type, base_type))
        candidates: list[type] = []
        seen: set[type] = set()
        for root_type in root_types:
            for candidate_type in root_type.__mro__:
                if candidate_type is object or candidate_type in seen:
                    continue
                candidates.append(candidate_type)
                seen.add(candidate_type)
        return tuple(candidates)


def register_inline_dataclass_widget(dataclass_type: type, widget_factory: InlineDataclassWidgetFactory) -> None:
    """Register the structural editor capability for a dataclass."""
    _InlineDataclassWidgetCatalog.register(dataclass_type, widget_factory)


class ParameterInfoMeta(ABCMeta):
    """Discover predicates from their declarations, never their import order."""

    _registry: list[type] = []

    def __new__(mcs, name, bases, namespace):
        cls = super().__new__(mcs, name, bases, namespace)
        if "matches" in namespace and callable(cls.matches):
            mcs._registry.append(cls)
        return cls

    @classmethod
    def select(mcs, root: type, annotation: object) -> type:
        matches = [kind for kind in mcs._registry
                   if issubclass(kind, root) and kind.matches(annotation)]
        if not matches:
            return root
        specific = [kind for kind in matches
                    if all(issubclass(kind, other) for other in matches)]
        if len(specific) != 1:
            names = ", ".join(sorted(kind.__qualname__ for kind in matches))
            raise TypeError(f"Ambiguous parameter declarations for {annotation!r}: {names}")
        return specific[0]


@dataclass
class ParameterInfo(metaclass=ParameterInfoMeta):
    """An admitted field; ordinary values are the family's concrete default."""

    name: str
    type: type
    current_value: ParameterValue | None
    description: str | None = None
    default_value: ParameterValue | None = None
    is_required: bool = True

    @classmethod
    def create(cls, name: str, param_type: type, current_value: ParameterValue | None,
               default_value: ParameterValue | None = None, description: str | None = None,
               is_required: bool = True) -> "ParameterInfo":
        kind = ParameterInfoMeta.select(cls, resolve_annotated(param_type))
        return kind(name=name, type=param_type, current_value=current_value,
                    default_value=default_value, description=description, is_required=is_required)

    def nested_form(self, service, analysis):
        """Ordinary values do not create a nested form."""
        return None


@dataclass
class DirectDataclassInfo(ParameterInfo):
    """A dataclass value with the ordinary nested-form presentation."""

    @staticmethod
    def matches(param_type: type) -> bool:
        return is_dataclass(param_type)

    def nested_form(self, service, analysis):
        return service.analyze_nested_parameter(self, analysis)


@dataclass
class OptionalInfo(ParameterInfo):
    """A nullable value; nullability is independent of its member's shape."""

    @staticmethod
    def matches(param_type: type) -> bool:
        return optional_member_type(param_type) is not None


@dataclass
class OptionalDataclassInfo(OptionalInfo, DirectDataclassInfo):
    """A nullable dataclass composes both declarations through C3 MRO."""

    @staticmethod
    def matches(param_type: type) -> bool:
        inner_type = optional_member_type(param_type)
        return inner_type is not None and is_dataclass(inner_type)


@dataclass
class InlineDataclassWidgetInfo(DirectDataclassInfo):
    """A dataclass with a structural widget factory.

    A frontend without that factory capability still has the dataclass
    presentation through the parent; it never calls another toolkit's factory.
    """

    @staticmethod
    def matches(param_type: type) -> bool:
        return is_dataclass(param_type) and _InlineDataclassWidgetCatalog.has_factory_for(param_type)

    def nested_form(self, service, analysis):
        # This frontend uses the structural value widget, not a nested manager.
        return None

    def widget_factory(self) -> InlineDataclassWidgetFactory:
        factory = _InlineDataclassWidgetCatalog.factory_for(resolve_annotated(self.type))
        if factory is None:
            raise ValueError(f"No inline dataclass widget registered for {self.type!r}")
        return factory
