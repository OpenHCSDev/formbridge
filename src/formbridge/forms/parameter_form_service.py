"""
Shared service layer for parameter form managers.

This module provides a framework-agnostic service layer that eliminates the
architectural dependency between PyQt and Textual implementations by providing
shared business logic and data management.

Uses React-style discriminated unions for type-safe parameter handling.
"""
from objectstate.field_value import Unset
from objectstate.declarations import ValueDeclaration
from objectstate.construction_binding import admit_target

import dataclasses
from collections.abc import (
    Callable as CallableABC,
)
from collections.abc import (
    Mapping as MappingABC,
)
from collections.abc import (
    Sequence as SequenceABC,
)
from dataclasses import dataclass
from typing import Any, get_args, get_origin, get_type_hints

from objectstate import (
    DataclassFieldAccess,
    LazyDefaultPlaceholderService,
    UIParameterVisibilityRequest,
    UIParameterVisibilityPolicy,
    has_lazy_resolution,
    should_hide_ui_parameter,
)
from python_introspect import (
    AnnotationChoices,
    coerce_enum_member,
    declared_annotation_choices,
    is_union_type,
    resolve_annotated,
    resolve_optional,
)

from formbridge.forms.parameter_form_constants import CONSTANTS
from formbridge.forms.parameter_info_types import ParameterInfo, create_parameter_info
from formbridge.forms.parameter_type_utils import ParameterTypeUtils
from formbridge.forms.parameter_value_contracts import (
    FormObject,
    NestedManagerMap,
    ParameterDefaultsByName,
    ParameterDescriptionByPath,
    ParameterDescriptionProvider,
    ParameterTypesByName,
    ParameterValue,
)
from formbridge.forms.ui_utils import FieldDisplayText, debug_param

_NO_CONVERSION = object()


def _type_label(param_type: type) -> str:
    """Return a stable label for diagnostics and tooltips."""
    return param_type.__name__ if isinstance(param_type, type) else str(param_type)


@dataclass
class ParameterAnalysisInput:
    """
    Type-safe input for parameter analysis.

    Field names match UnifiedParameterInfo for automatic extraction.
    This enforces unification across all functions that analyze parameters.
    """

    default_value: ParameterDefaultsByName
    param_type: dict[str, type]
    field_id: str
    # Dotted-path description map (may be provided lazily via a callable).
    description: ParameterDescriptionByPath | ParameterDescriptionProvider | None = None
    parent_obj_type: type | None = None


@dataclass
class FormStructure:
    """
    Structure information for a parameter form.

    Uses discriminated union ParameterInfo types for type-safe dispatch.

    Attributes:
        field_id: Unique identifier for the form
        parameters: List of parameter information (discriminated union types)
        nested_forms: Dictionary of nested form structures
        has_optional_dataclasses: Whether form has optional dataclass parameters
    """

    field_id: str
    parameters: list[ParameterInfo]
    nested_forms: dict[str, "FormStructure"]
    @property
    def has_optional_dataclasses(self) -> bool:
        return any(info.optional_parameters() for info in self.parameters)

    def get_parameter_info(self, param_name: str) -> ParameterInfo | None:
        """
        Get ParameterInfo for a parameter by name.

        Args:
            param_name: Name of the parameter

        Returns:
            ParameterInfo instance (discriminated union type) or None if not found

        Note:
            Returns None for parameters like 'enabled' that are rendered in header
            and not part of the regular form structure.
        """
        for param_info in self.parameters:
            if param_info.name == param_name:
                return param_info
        return None


class ParameterFormService:
    """
    Framework-agnostic service for parameter form business logic.

    This service provides shared functionality for both PyQt and Textual
    parameter form managers, eliminating the need for cross-framework
    dependencies and providing a clean separation of concerns.
    """

    def __init__(self):
        """
        Initialize the parameter form service.
        """
        self._type_utils = ParameterTypeUtils()

    def analyze_parameters(self, input: ParameterAnalysisInput) -> FormStructure:
        parameters = []
        nested_forms = {}
        for name, annotation in input.param_type.items():
            if self._should_hide_from_ui(input.parent_obj_type, name, annotation):
                continue
            full_path = f"{input.field_id}.{name}" if input.field_id else name
            info = self._create_parameter_info(
                name, annotation, input.default_value.get(name, Unset()), input.description, full_path,
            )
            parameters.append(info)
            nested_forms.update(info.nested_forms(self, input))
        return FormStructure(field_id=input.field_id, parameters=parameters, nested_forms=nested_forms)

    def _should_hide_from_ui(
        self,
        parent_obj_type: type | None,
        param_name: str,
        param_type: type,
    ) -> bool:
        """
        Check if a parameter should be hidden from the UI.

        Args:
            parent_obj_type: The parent dataclass type (None for function parameters)
            param_name: Name of the parameter
            param_type: Type of the parameter

        Returns:
            True if the parameter should be hidden from UI
        """
        return should_hide_ui_parameter(
            UIParameterVisibilityRequest(
                owner_type=parent_obj_type,
                field_name=param_name,
                field_type_candidate=resolve_optional(resolve_annotated(param_type)),
                field_metadata_hidden=self._field_metadata_declares_hidden(
                    parent_obj_type,
                    param_name,
                ),
            )
        )


    def _field_metadata_declares_hidden(self, parent_obj_type, param_name) -> bool:
        return any(item.name == param_name and UIParameterVisibilityPolicy.field_hidden(item)
                   for owner in ValueDeclaration.of(parent_obj_type).configuration_owners()
                   for item in owner.declared_fields())

    def convert_value_to_type(
        self, value: ParameterValue, param_type: type, param_name: str, obj_type: type = None
    ) -> ParameterValue:
        """Convert domain input through its annotation; retain field directives."""
        return ValueDeclaration.of(param_type).admit(value).map(
            lambda raw: self._convert_domain_value(raw, param_type, param_name, obj_type)
        )

    def _convert_domain_value(
        self, value: ParameterValue, param_type: type, param_name: str, obj_type: type = None
    ) -> ParameterValue | None:
        """
        Convert a value to the appropriate type for a parameter.

        This method provides centralized type conversion logic that can be
        used by any UI framework.

        Args:
            value: The value to convert
            param_type: The target parameter type
            param_name: The parameter name (for debugging)
            obj_type: The dataclass type (for sibling inheritance checks)

        Returns:
            The converted value
        """
        debug_param(
            "convert_value",
            f"param={param_name}, input_type={type(value).__name__}, "
            f"target_type={_type_label(param_type)}",
        )

        if value is None:
            return None

        choices = declared_annotation_choices(param_type)
        if choices is not None:
            return self._convert_choice_value(value, choices, param_name)

        resolved_type = resolve_annotated(param_type)
        structured_value = self._convert_value_by_annotation(
            value,
            resolved_type,
            param_name,
        )
        if structured_value is not _NO_CONVERSION:
            return structured_value

        # Handle enum types
        if self._type_utils.is_enum_type(resolved_type):
            return coerce_enum_member(resolved_type, value)

        # Handle list of enums
        if self._type_utils.is_list_of_enums(resolved_type):
            # If value is already a list (from checkbox group widget), return as-is
            if isinstance(value, list):
                return value
            enum_type = self._type_utils.get_enum_from_list_type(resolved_type)
            if enum_type:
                return [coerce_enum_member(enum_type, value)]

        # Handle basic types
        if resolved_type is bool and isinstance(value, str):
            return self._type_utils.convert_string_to_bool(value)
        if resolved_type in (int, float) and isinstance(value, str):
            if value == CONSTANTS.EMPTY_STRING:
                return Unset()
            try:
                return resolved_type(value)
            except (ValueError, TypeError) as exc:
                raise ValueError(
                    f"Invalid {resolved_type.__name__} value for parameter "
                    f"{param_name!r}: {value!r}"
                ) from exc

        return value

    def _convert_value_by_annotation(
        self,
        value: ParameterValue,
        param_type: type,
        param_name: str,
    ) -> ParameterValue | object:
        """Recursively rebuild structured values from JSON-like containers."""
        choices = declared_annotation_choices(param_type)
        if choices is not None and value is not None:
            return self._convert_choice_value(value, choices, param_name)
        param_type = resolve_annotated(param_type)
        origin = get_origin(param_type)

        if origin is type:
            return value if isinstance(value, type) else _NO_CONVERSION

        if param_type is CallableABC or origin is CallableABC:
            return value if callable(value) else _NO_CONVERSION

        if is_union_type(param_type):
            return self._convert_union_value(value, param_type, param_name)

        if self._type_utils.is_enum_type(param_type):
            if isinstance(value, param_type):
                return value
            return coerce_enum_member(param_type, value)

        return ValueDeclaration.of(param_type).convert_structure(self, value, param_name)

    def convert_leaf_structure(self, value, param_type, param_name):
        origin = get_origin(param_type)
        if origin in (tuple, SequenceABC):
            return self._convert_tuple_value(value, param_type, param_name)
        if origin is list:
            return self._convert_list_value(value, param_type, param_name)
        if origin in (dict, MappingABC):
            return self._convert_dict_value(value, param_type, param_name)
        return _NO_CONVERSION

    @staticmethod
    def _convert_choice_value(
        value: ParameterValue,
        choices: AnnotationChoices,
        param_name: str,
    ) -> ParameterValue:
        """Decode declared choices (or their labels) for one choice field."""

        admitted = choices.choices()

        def decode(item: ParameterValue) -> ParameterValue:
            if item in admitted:
                return item
            if isinstance(item, str):
                return choices.choice_for_label(item)
            raise ValueError(
                f"Invalid choice for parameter {param_name!r}: {item!r}; expected "
                f"one of {[choices.label(choice) for choice in admitted]}."
            )

        if isinstance(value, (list, tuple)):
            return type(value)(decode(item) for item in value)
        return decode(value)

    def _convert_union_value(
        self,
        value: ParameterValue,
        param_type: type,
        param_name: str,
    ) -> ParameterValue | object:
        last_error: Exception | None = None
        for candidate_type in get_args(param_type):
            if candidate_type is type(None):
                continue
            candidate_type = resolve_annotated(candidate_type)
            try:
                converted = self._convert_value_by_annotation(
                    value,
                    candidate_type,
                    param_name,
                )
            except Exception as exc:
                last_error = exc
                continue
            if converted is not _NO_CONVERSION:
                return converted
            if isinstance(candidate_type, type) and isinstance(value, candidate_type):
                if candidate_type is int and type(value) is bool:
                    continue
                return value
            if candidate_type is float and type(value) is int:
                return float(value)
        if last_error is not None:
            raise last_error
        raise ValueError(
            f"Invalid value for parameter {param_name!r}: "
            f"expected {_type_label(param_type)}, got {type(value).__name__}."
        )


    def _convert_tuple_value(
        self,
        value: ParameterValue,
        param_type: type,
        param_name: str,
    ) -> ParameterValue | object:
        if not isinstance(value, (list, tuple)):
            return _NO_CONVERSION

        args = get_args(param_type)
        if get_origin(param_type) is SequenceABC:
            item_type = args[0] if args else Any
            return tuple(
                self._converted_container_item(item, item_type, param_name) for item in value
            )
        if len(args) == 2 and args[1] is Ellipsis:
            item_type = args[0]
            return tuple(
                self._converted_container_item(item, item_type, param_name) for item in value
            )

        if args and len(value) != len(args):
            raise ValueError(
                f"Invalid tuple length for parameter {param_name!r}: "
                f"expected {len(args)}, got {len(value)}."
            )
        if not args:
            return tuple(value)

        return tuple(
            self._converted_container_item(item, item_type, param_name)
            for item, item_type in zip(value, args)
        )

    def _convert_list_value(
        self,
        value: ParameterValue,
        param_type: type,
        param_name: str,
    ) -> ParameterValue | object:
        if not isinstance(value, list):
            return _NO_CONVERSION

        args = get_args(param_type)
        if not args:
            return value
        item_type = args[0]
        return [self._converted_container_item(item, item_type, param_name) for item in value]

    def _convert_dict_value(
        self,
        value: ParameterValue,
        param_type: type,
        param_name: str,
    ) -> ParameterValue | object:
        if not isinstance(value, dict):
            return _NO_CONVERSION

        args = get_args(param_type)
        if len(args) != 2:
            return value

        key_type, item_type = args
        return {
            self._converted_container_item(
                key, key_type, param_name
            ): self._converted_container_item(item, item_type, param_name)
            for key, item in value.items()
        }

    def _converted_container_item(
        self,
        value: ParameterValue,
        item_type: type,
        param_name: str,
    ) -> ParameterValue:
        item_type = resolve_annotated(item_type)
        converted = self._convert_value_by_annotation(
            value,
            item_type,
            param_name,
        )
        if converted is not _NO_CONVERSION:
            return converted

        if item_type is Any:
            return value

        if item_type is float and type(value) is int:
            return float(value)

        if isinstance(item_type, type) and isinstance(value, item_type):
            if item_type is int and type(value) is bool:
                raise ValueError(
                    f"Invalid item for parameter {param_name!r}: expected int, got bool."
                )
            return value

        raise ValueError(
            f"Invalid item for parameter {param_name!r}: "
            f"expected {_type_label(item_type)}, got {type(value).__name__}."
        )

    def get_parameter_display_info(
        self, param_name: str, param_type: type, description: str | None = None
    ) -> dict[str, str]:
        """
        Get display information for a parameter.

        Args:
            param_name: The parameter name
            param_type: The parameter type
            description: Optional parameter description

        Returns:
            Dictionary with display information
        """
        text = FieldDisplayText.from_field_name(param_name)
        return {
            "display_name": text.display_name,
            "field_label": text.field_label,
            "checkbox_label": text.checkbox_label,
            "group_title": text.group_title,
            "description": description or f"Parameter: {text.display_name}",
            "tooltip": f"{text.display_name} ({_type_label(param_type)})",
        }


    def generate_field_ids_direct(self, base_field_id: str, param_name: str) -> dict[str, str]:
        """Generate field IDs directly without artificial complexity."""
        widget_id = f"{base_field_id}_{param_name}"
        return {
            "field_id": base_field_id,
            "widget_id": widget_id,
            "reset_button_id": f"reset_{widget_id}",
            "optional_checkbox_id": f"{base_field_id}_{param_name}_enabled",
        }


    def extract_nested_parameters(self, dataclass_instance, obj_type, parent_obj_type=None):
        source = admit_target(dataclass_instance)
        declaration = ValueDeclaration.of(obj_type)
        parameters = ParameterDefaultsByName()
        parameter_types = ParameterTypesByName()
        annotations = declaration.field_annotations()
        for name in source.declaration.parameters:
            parameters[name] = source.read_raw(name).stored
            parameter_types[name] = annotations[name]
        return parameters, parameter_types


    def _create_parameter_info(
        self,
        param_name: str,
        param_type: type,
        current_value: ParameterValue,
        parameter_info: dict | None = None,
        full_param_path: str = None,
    ) -> ParameterInfo:
        """
        Create parameter information object using discriminated union factory.

        Uses type introspection to automatically select the correct ParameterInfo
        subclass (OptionalDataclassInfo, DirectDataclassInfo, or GenericInfo).
        """
        description = None
        resolved_info = parameter_info() if callable(parameter_info) else parameter_info
        if isinstance(resolved_info, dict) and full_param_path:
            description = resolved_info.get(full_param_path)

        # Use factory to create correct ParameterInfo subclass
        # Factory uses type introspection to determine which type to create
        return create_parameter_info(
            name=param_name,
            param_type=param_type,
            current_value=current_value,
            description=description,
        )

    # Class-level cache for nested dataclass parameter info (descriptions only)
    _nested_param_info_cache = {}

    def _analyze_nested_dataclass(
        self,
        param_name: str,
        param_type: type,
        current_value: ParameterValue | None,
        nested_field_id: str,
        parent_obj_type: type = None,
    ) -> FormStructure:
        """Analyze a nested dataclass parameter."""
        # Get the actual dataclass type
        obj_type = resolve_optional(resolve_annotated(param_type))

        # Extract nested parameters using parent context
        nested_params, nested_types = self.extract_nested_parameters(
            current_value, obj_type, parent_obj_type
        )

        # OPTIMIZATION: Cache parameter info (descriptions) by dataclass type
        # We only need descriptions, not instance values, so analyze the type once and reuse
        cache_key = obj_type
        if cache_key in self._nested_param_info_cache:
            nested_param_info = self._nested_param_info_cache[cache_key]
        else:
            # Recursively analyze nested structure with proper descriptions for nested fields
            # Use existing infrastructure to extract field descriptions for the nested dataclass
            from python_introspect import UnifiedParameterAnalyzer

            # OPTIMIZATION: Always analyze the TYPE, not the instance
            # This allows caching and avoids extracting field values we don't need
            nested_param_info = UnifiedParameterAnalyzer.analyze(obj_type)
            self._nested_param_info_cache[cache_key] = nested_param_info

        # Create type-safe input for recursive analysis
        # CRITICAL FIX: Use dotted paths for descriptions to match state._parameter_descriptions
        # This ensures lookups work correctly when descriptions come from ObjectState
        description = ParameterDescriptionByPath()
        if nested_param_info:
            prefix = f"{nested_field_id}." if nested_field_id else ""
            description = ParameterDescriptionByPath(
                (f"{prefix}{name}", info.description) for name, info in nested_param_info.items()
            )

        nested_input = ParameterAnalysisInput(
            default_value=nested_params,
            param_type=nested_types,
            field_id=nested_field_id,
            description=description,
            parent_obj_type=obj_type,
        )

        return self.analyze_parameters(nested_input)

    def get_placeholder_text(
        self, param_name: str, obj_type: type, placeholder_prefix: str = "Pipeline default"
    ) -> str | None:
        """
        Get placeholder text from the lazy-resolution context.

        Context must be established by the caller using config_context() before calling this method.
        This allows the caller to build proper context stacks (parent + overlay) for accurate
        placeholder resolution.

        Args:
            param_name: Name of the parameter to get placeholder for
            obj_type: The specific dataclass type (GlobalPipelineConfig or PipelineConfig)
            placeholder_prefix: Prefix for the placeholder text

        Returns:
            Formatted placeholder text or None if no resolution possible

        The editing mode is derived from the dataclass type's lazy resolution capabilities:
        - Has lazy resolution (PipelineConfig) → orchestrator config editing
        - No lazy resolution (GlobalPipelineConfig) → global config editing
        """
        # Service just resolves placeholders, caller manages context
        return LazyDefaultPlaceholderService.get_lazy_resolved_placeholder(
            obj_type, param_name, placeholder_prefix
        )

    def reset_nested_managers(
        self, nested_managers: NestedManagerMap, obj_type: type, current_config
    ) -> None:
        """Reset all nested managers - fail loud, no defensive programming."""
        for nested_manager in nested_managers.values():
            # All nested managers must have reset_all_parameters method
            nested_manager.reset_all_parameters()
