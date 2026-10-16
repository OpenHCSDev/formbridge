"""Parameter declarations select their UI behavior through admitted values."""

from abc import ABC
from collections.abc import Callable
from dataclasses import dataclass

from objectstate.field_value import FieldValue, Unset
from objectstate.declarations import ValueDeclaration
from python_introspect import optional_member_type, resolve_annotated, resolve_declared_type

from formbridge.forms.parameter_value_contracts import ParameterValue

InlineDataclassWidgetFactory = Callable


class _InlineDataclassWidgetCatalog:
    """Authority for registered structural editors, not configuration kinds."""

    _factories: dict[type, InlineDataclassWidgetFactory] = {}

    @classmethod
    def register(cls, dataclass_type: type, widget_factory: InlineDataclassWidgetFactory) -> None:
        ValueDeclaration.of(dataclass_type).require_config_type()
        dataclass_type = resolve_declared_type(dataclass_type)
        registered = cls._factories.get(dataclass_type)
        if registered is not None and registered is not widget_factory:
            raise ValueError(f"{dataclass_type.__qualname__} already has an inline widget factory ({registered!r}); it cannot also use {widget_factory!r}.")
        cls._factories[dataclass_type] = widget_factory

    @classmethod
    def factory_for(cls, dataclass_type: type) -> InlineDataclassWidgetFactory | None:
        for candidate in resolve_declared_type(dataclass_type).__mro__:
            if candidate in cls._factories:
                return cls._factories[candidate]
        return None

    @classmethod
    def declaration(cls, declared_type, **arguments):
        factory = cls.factory_for(declared_type)
        return DirectDataclassInfo(**arguments) if factory is None else InlineDataclassWidgetInfo(**arguments)


def register_inline_dataclass_widget(dataclass_type: type, widget_factory: InlineDataclassWidgetFactory) -> None:
    _InlineDataclassWidgetCatalog.register(dataclass_type, widget_factory)


@dataclass
class ParameterInfoBase(ABC):
    name: str
    type: type
    current_value: ParameterValue
    description: str | None = None
    default_value: ParameterValue = Unset()
    is_required: bool = True
    def creation_type(self, kinds):
        return kinds.REGULAR

    @classmethod
    def scalar_declaration(cls, declared_type, *, nullable=False, **arguments):
        return GenericInfo(**arguments)

    @classmethod
    def config_declaration(cls, declared_type, *, nullable=False, **arguments):
        if nullable:
            return OptionalDataclassInfo(**arguments)
        return _InlineDataclassWidgetCatalog.declaration(declared_type, **arguments)

    def nested_forms(self, service, analysis_input):
        return {}

    def optional_parameters(self):
        return ()


@dataclass
class DirectDataclassInfo(ParameterInfoBase):
    def creation_type(self, kinds):
        return kinds.NESTED

    def nested_forms(self, service, analysis_input):
        return {self.name: service._analyze_nested_dataclass(
            self.name, self.type, self.current_value, self.name, analysis_input.parent_obj_type,
        )}


@dataclass
class OptionalDataclassInfo(DirectDataclassInfo):
    def creation_type(self, kinds):
        return kinds.OPTIONAL_NESTED

    def optional_parameters(self):
        return (self,)


@dataclass
class InlineDataclassWidgetInfo(ParameterInfoBase):
    def creation_type(self, kinds):
        return kinds.INLINE_DATACLASS

    def widget_factory(self) -> InlineDataclassWidgetFactory:
        factory = _InlineDataclassWidgetCatalog.factory_for(resolve_annotated(self.type))
        if factory is None:
            raise ValueError(f"No inline dataclass widget registered for {self.type!r}.")
        return factory


@dataclass
class GenericInfo(ParameterInfoBase):
    pass


ParameterInfo = OptionalDataclassInfo | InlineDataclassWidgetInfo | DirectDataclassInfo | GenericInfo


def create_parameter_info(
    name: str,
    param_type: type,
    current_value: ParameterValue,
    default_value: ParameterValue = Unset(),
    description: str | None = None,
    is_required: bool = True,
) -> ParameterInfo:
    annotation = resolve_annotated(param_type)
    inner = optional_member_type(annotation)
    declaration = ValueDeclaration.of(annotation if inner is None else resolve_annotated(inner))
    return declaration.choose_declaration(
        ParameterInfoBase,
        nullable=inner is not None,
        name=name, type=param_type, current_value=current_value,
        default_value=default_value, description=description, is_required=is_required,
    )
