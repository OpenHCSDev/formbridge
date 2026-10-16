"""
Shared service layer for parameter form managers.

This module provides a framework-agnostic service layer that eliminates the
architectural dependency between PyQt and Textual implementations by providing
shared business logic and data management.

Uses React-style discriminated unions for type-safe parameter handling.
"""

import dataclasses
from collections.abc import (
    Callable as CallableABC,
)
from collections.abc import (
    Iterator,
    Mapping as MappingABC,
)
from collections.abc import (
    Sequence as SequenceABC,
)
from dataclasses import dataclass
from typing import Any, get_args, get_origin, get_type_hints

from objectstate import (
    DataclassFieldAccess,
    DottedFieldPath,
    LazyDefaultPlaceholderService,
    ObjectState,
    UIParameterVisibilityRequest,
    has_lazy_resolution,
    should_hide_ui_parameter,
)
from python_introspect import (
    AnnotationChoices,
    UnifiedParameterAnalyzer,
    coerce_enum_member,
    declared_annotation_choices,
    is_union_type,
    resolve_annotated,
)

from formbridge.forms.parameter_form_constants import CONSTANTS
from formbridge.forms.parameter_info_types import OptionalDataclassInfo, ParameterInfo
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
        return any(isinstance(info, OptionalDataclassInfo) for info in self.parameters)

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

    def parameters_for_state(
        self, state: ObjectState, parent_path: str = ""
    ) -> Iterator[tuple[DottedFieldPath, ParameterInfo]]:
        """Present admitted paths and their kinds without extracting a second form tree.

        ObjectState owns the declarations, order and current values. This
        service owns UI visibility and field-kind selection, for every frontend.
        The yielded information is consumed immediately, not retained as state.
        """
        parent_type = state.type_for_path(parent_path)
        for path in state.direct_parameter_paths(parent_path):
            declaration = state.parameter_structure.declarations[path.value]
            name = declaration.name
            if self._should_hide_from_ui(parent_type, name, declaration.param_type):
                continue
            yield path, ParameterInfo.create(
                name=name,
                param_type=declaration.param_type,
                current_value=state.get_resolved_value(path.value),
                default_value=declaration.default_value,
                description=declaration.description,
                is_required=declaration.is_required,
            )

    def analyze_parameters(self, input: ParameterAnalysisInput) -> FormStructure:
        """
        Analyze parameters and create form structure.

        This method analyzes the parameters and their types to create a complete
        form structure that can be used by any UI framework.

        Args:
            input: Type-safe parameter analysis input (field names match UnifiedParameterInfo)

        Returns:
            Complete form structure information
        """
        debug_param(
            "analyze_parameters",
            f"field_id={input.field_id}, parameter_count={len(input.default_value)}",
        )

        import logging

        logger = logging.getLogger(__name__)
        logger.debug(
            "analyze_parameters: field_id=%s param_type.keys()=%s",
            input.field_id,
            list(input.param_type.keys()),
        )

        param_infos = []
        nested_forms = {}

        for param_name, parameter_type in input.param_type.items():
            current_value = input.default_value.get(param_name)

            # Check if this parameter should be hidden from UI
            if self._should_hide_from_ui(input.parent_obj_type, param_name, parameter_type):
                debug_param(
                    "analyze_parameters", f"Hiding parameter {param_name} from UI (ui_hidden=True)"
                )
                continue

            # CRITICAL FIX: Build full dotted path for description lookup
            # When nested_field_id is set (e.g., "well_filter_config"), pass the full
            # dotted path to _create_parameter_info so it builds the key that
            # state._parameter_descriptions uses (dotted paths).
            full_param_path = f"{input.field_id}.{param_name}" if input.field_id else param_name

            # Create parameter info with full dotted path
            param_info = self._create_parameter_info(
                param_name, parameter_type, current_value, input.description, full_param_path
            )
            param_infos.append(param_info)

            nested_structure = param_info.nested_form(self, input)
            if nested_structure is not None:
                nested_forms[param_name] = nested_structure

        return FormStructure(
            field_id=input.field_id,
            parameters=param_infos,
            nested_forms=nested_forms,
        )

    def analyze_nested_parameter(self, info: ParameterInfo, analysis: ParameterAnalysisInput) -> FormStructure:
        """Build the nested presentation requested by the admitted kind."""
        unwrapped_type = self._unwrap_optional_dataclass_type(info.type)
        nested_field_id = (info.name if analysis.parent_obj_type is None else
                           self.resolve_declared_field_path(analysis.parent_obj_type, info.name, unwrapped_type))
        return self._analyze_nested_dataclass(
            info.name, info.type, info.current_value, nested_field_id, analysis.parent_obj_type,
        )

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
                field_type_candidate=self._unwrap_optional_dataclass_type(param_type),
                field_metadata_hidden=self._field_metadata_declares_hidden(
                    parent_obj_type,
                    param_name,
                ),
            )
        )

    def _unwrap_optional_dataclass_type(self, param_type: type) -> type:
        """Return the structural type, retaining metadata on the declaration."""
        param_type = resolve_annotated(param_type)
        if self._type_utils.is_optional_dataclass(param_type):
            return self._type_utils.get_optional_inner_type(param_type)
        return param_type

    def _field_metadata_declares_hidden(
        self,
        parent_obj_type: type | None,
        param_name: str,
    ) -> bool:
        """Return True when a dataclass field carries UI-hidden metadata."""
        if parent_obj_type is None:
            return False
        if not dataclasses.is_dataclass(parent_obj_type):
            return False

        field_by_name = {field.name: field for field in dataclasses.fields(parent_obj_type)}
        field_obj = field_by_name.get(param_name)
        if field_obj is None:
            return False
        return field_obj.metadata.get("ui_hidden", False)

    def convert_value_to_type(
        self, value: ParameterValue, param_type: type, param_name: str
    ) -> ParameterValue | None:
        """
        Convert a value to the appropriate type for a parameter.

        This method provides centralized type conversion logic that can be
        used by any UI framework.

        Args:
            value: The value to convert
            param_type: The target parameter type
            param_name: The parameter name (for debugging)

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

        # Handle string "None" literal
        if isinstance(value, str) and value == CONSTANTS.NONE_STRING_LITERAL:
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
                return None
            try:
                return resolved_type(value)
            except (ValueError, TypeError) as exc:
                raise ValueError(
                    f"Invalid {resolved_type.__name__} value for parameter "
                    f"{param_name!r}: {value!r}"
                ) from exc

        # Handle empty strings in lazy context - convert to None for all parameter types
        # This is critical for lazy dataclass behavior where None triggers placeholder resolution
        if isinstance(value, str) and value == CONSTANTS.EMPTY_STRING:
            return None

        # Handle string types - also convert empty strings to None for consistency
        if resolved_type is str and isinstance(value, str) and value == CONSTANTS.EMPTY_STRING:
            return None

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

        if dataclasses.is_dataclass(param_type):
            return self._convert_dataclass_value(value, param_type, param_name)

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

    def _convert_dataclass_value(
        self,
        value: ParameterValue,
        dataclass_type: type,
        param_name: str,
    ) -> ParameterValue | object:
        if isinstance(value, dataclass_type):
            return value
        if not isinstance(value, dict):
            return _NO_CONVERSION

        try:
            type_hints = get_type_hints(dataclass_type, include_extras=True)
        except Exception:
            type_hints = {}

        kwargs = {}
        for field in dataclasses.fields(dataclass_type):
            if field.name not in value:
                continue
            field_value = value[field.name]
            field_type = type_hints.get(field.name, field.type)
            converted = self._convert_value_by_annotation(
                field_value,
                field_type,
                field.name,
            )
            kwargs[field.name] = field_value if converted is _NO_CONVERSION else converted

        try:
            return dataclass_type(**kwargs)
        except Exception as exc:
            raise ValueError(
                f"Invalid dataclass value for parameter {param_name!r}: {value!r}"
            ) from exc

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

    def resolve_declared_field_path(
        self,
        parent_type: type,
        param_name: str,
        param_type: type,
    ) -> str:
        """Validate and return the already-declared nested field name."""
        if not param_name:
            raise ValueError("Nested form field name cannot be empty.")

        if not dataclasses.is_dataclass(parent_type):
            return param_name

        try:
            field_types = get_type_hints(parent_type)
        except Exception as exc:
            raise ValueError(f"Cannot resolve declared fields for {parent_type!r}.") from exc

        if param_name not in field_types:
            raise ValueError(f"{parent_type.__name__} has no declared field {param_name!r}.")

        declared_type = self._unwrap_optional_dataclass_type(field_types[param_name])
        if declared_type is not param_type:
            raise ValueError(
                f"{parent_type.__name__}.{param_name} declares "
                f"{_type_label(declared_type)}, not {_type_label(param_type)}."
            )
        return param_name

    def generate_field_ids_direct(self, base_field_id: str, param_name: str) -> dict[str, str]:
        """Generate field IDs directly without artificial complexity."""
        widget_id = f"{base_field_id}_{param_name}"
        return {
            "field_id": base_field_id,
            "widget_id": widget_id,
            "reset_button_id": f"reset_{widget_id}",
            "optional_checkbox_id": f"{base_field_id}_{param_name}_enabled",
        }

    def should_use_concrete_values(
        self, current_value: ParameterValue | None, is_global_editing: bool = False
    ) -> bool:
        """
        Determine whether to use concrete values for a dataclass parameter.

        Args:
            current_value: The current parameter value
            is_global_editing: Whether in global configuration editing mode

        Returns:
            True if concrete values should be used
        """
        if current_value is None:
            return False

        if is_global_editing:
            return True

        # If current_value is a concrete dataclass instance, use its values
        if self._type_utils.is_concrete_dataclass(current_value):
            return True

        # For lazy dataclasses, return True so we can extract raw values from them
        if self._type_utils.is_lazy_dataclass(current_value):
            return True

        return False

    def extract_nested_parameters(
        self,
        dataclass_instance: FormObject | None,
        obj_type: type,
        parent_obj_type: type | None = None,
    ) -> tuple[ParameterDefaultsByName, ParameterTypesByName]:
        """
        Extract parameters and types from a dataclass instance.

        This method always preserves concrete field values when a dataclass instance exists,
        regardless of parent context. Placeholder behavior is handled at the widget level,
        not by discarding concrete values during parameter extraction.
        """
        if not dataclasses.is_dataclass(obj_type):
            return ParameterDefaultsByName(), ParameterTypesByName()

        parameters = ParameterDefaultsByName()
        parameter_types = ParameterTypesByName()

        for name, declaration in UnifiedParameterAnalyzer.analyze(obj_type).items():
            parameters[name] = (
                DataclassFieldAccess.raw_value(dataclass_instance, name)
                if dataclass_instance is not None else None
            )
            parameter_types[name] = declaration.param_type

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
        most specific admitted ParameterInfo subclass.
        """
        description = None
        resolved_info = parameter_info() if callable(parameter_info) else parameter_info
        if isinstance(resolved_info, dict) and full_param_path:
            description = resolved_info.get(full_param_path)

        # Use factory to create correct ParameterInfo subclass
        # Factory uses type introspection to determine which type to create
        return ParameterInfo.create(
            name=param_name,
            param_type=param_type,
            current_value=current_value,
            description=description,
        )

    def _analyze_nested_dataclass(
        self,
        param_name: str,
        param_type: type,
        current_value: ParameterValue | None,
        nested_field_id: str,
        parent_obj_type: type = None,
    ) -> FormStructure:
        """Analyze a nested dataclass parameter."""
        obj_type = self._unwrap_optional_dataclass_type(param_type)

        # Extract nested parameters using parent context
        nested_params, nested_types = self.extract_nested_parameters(
            current_value, obj_type, parent_obj_type
        )

        # SignatureAnalyzer owns declaration caching and lazy help materialization.
        nested_param_info = UnifiedParameterAnalyzer.analyze(obj_type)

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

    def get_reset_value_for_parameter(
        self,
        param_name: str,
        param_type: type,
        obj_type: type,
        is_global_config_editing: bool | None = None,
    ) -> ParameterValue | None:
        """
        Get the reset value for one parameter.

        Args:
            param_name: Name of the parameter to reset
            param_type: Type of the parameter (int, str, bool, etc.)
            obj_type: The specific dataclass type
            is_global_config_editing: Whether global config is being edited (detected if None)

        Returns:
            - For global config editing: Actual default values
            - For lazy config editing: None to show placeholder text
        """
        # Context-driven behavior: Use the editing context to determine reset behavior
        # This follows the architectural principle that behavior is determined by context
        # of usage rather than intrinsic properties of the dataclass.

        # Context-driven behavior: Use explicit context when provided
        # Auto-detect editing mode if not explicitly provided
        if is_global_config_editing is None:
            is_global_config_editing = not has_lazy_resolution(obj_type)

        # Context-driven behavior: Reset behavior depends on editing context
        if is_global_config_editing:
            # Global config editing: Reset to actual default values
            # Users expect to see concrete defaults when editing global configuration
            return self._get_actual_dataclass_field_default(param_name, obj_type)
        else:
            # CRITICAL FIX: For lazy config editing, always return None
            # This ensures reset shows inheritance chain values (like compiler resolution)
            # instead of concrete values from thread-local context
            return None

    def _get_actual_dataclass_field_default(
        self, param_name: str, obj_type: type
    ) -> ParameterValue | None:
        """
        Get the actual default value for a parameter.

        Works uniformly for dataclasses, functions, and any other object type.
        Always returns None for non-existent fields (fail-soft for dynamic properties).

        Returns:
        - If class attribute is None → return None (show placeholder)
        - If class attribute has concrete value → return that value
        - If field(default_factory) → call default_factory and return result
        - If field doesn't exist → return None (dynamic property)
        """
        import inspect
        from dataclasses import MISSING, fields, is_dataclass

        # For pure functions: get default from signature
        if callable(obj_type) and not is_dataclass(obj_type) and not inspect.isclass(obj_type):
            sig = inspect.signature(obj_type)
            if param_name in sig.parameters:
                default = sig.parameters[param_name].default
                return None if default is inspect.Parameter.empty else default
            return None  # Dynamic property, not in signature

        # For all other types (dataclasses, ABCs, classes): check class attribute first
        sentinel = object()
        class_value = inspect.getattr_static(obj_type, param_name, sentinel)
        if class_value is not sentinel:
            return class_value

        # For dataclasses: check if it's a field(default_factory=...) field
        if is_dataclass(obj_type):
            dataclass_fields = {f.name: f for f in fields(obj_type)}
            if param_name not in dataclass_fields:
                return None  # Dynamic property, not a dataclass field

            field_info = dataclass_fields[param_name]

            # Handle field(default_factory=...) case
            if field_info.default_factory is not MISSING:
                try:
                    return field_info.default_factory()
                except Exception as e:
                    raise ValueError(
                        f"Failed to call default_factory for field '{param_name}': {e}"
                    ) from e

            # Handle field with explicit default
            if field_info.default is not MISSING:
                return field_info.default

            # Field has no default (should not happen in practice)
            return None

        # For non-dataclass types: return None (dynamic property)
        return None
