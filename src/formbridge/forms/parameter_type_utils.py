"""
Parameter type utilities for parameter form managers.

This module provides centralized type checking and resolution methods to eliminate
code duplication between PyQt and Textual parameter form implementations.
"""

from enum import Enum

from objectstate.lazy_factory import LazyDataclass
from objectstate.field_access import DataclassFieldAccess
from python_introspect import (
    get_enum_from_list,
    optional_member_type,
)
from python_introspect import (
    is_enum_type as annotation_is_enum_type,
)
from python_introspect import (
    is_list_of_enums as annotation_is_list_of_enums,
)

from formbridge.forms.parameter_form_constants import CONSTANTS


class ParameterTypeUtils:
    """
    Utility class for parameter type checking and resolution.

    This class provides static methods for common type operations used throughout
    the parameter form system, including Optional type handling, dataclass detection,
    and Union type resolution.
    """

    @staticmethod
    def is_optional(param_type: type) -> bool:
        """
        Check if parameter type is Optional[T] (Union[T, None]).

        This method determines whether a type annotation represents an optional
        parameter of any type.

        Args:
            param_type: The type to check

        Returns:
            True if the type is Optional[T], False otherwise

        Example:
            >>> from typing import Optional
            >>> ParameterTypeUtils.is_optional(Optional[str])
            True
            >>> ParameterTypeUtils.is_optional(str)
            False
        """
        return optional_member_type(param_type) is not None

    @staticmethod
    def is_optional_dataclass(param_type: type) -> bool:
        """
        Check if parameter type is Optional[dataclass].

        This method determines whether a type annotation represents an optional
        dataclass parameter (Union[DataclassType, None]).

        Args:
            param_type: The type to check

        Returns:
            True if the type is Optional[dataclass], False otherwise

        Example:
            >>> from typing import Optional
            >>> @dataclass
            ... class Config: pass
            >>> ParameterTypeUtils.is_optional_dataclass(Optional[Config])
            True
            >>> ParameterTypeUtils.is_optional_dataclass(Config)
            False
        """
        optional_type = optional_member_type(param_type)
        return DataclassFieldAccess.is_config_type(optional_type)

    @staticmethod
    def get_optional_inner_type(param_type: type) -> type:
        """
        Extract the inner type from Optional[T].

        This method extracts the non-None type from an Optional type annotation.

        Args:
            param_type: The Optional type to extract from

        Returns:
            The inner type (T from Optional[T])

        Raises:
            ValueError: If the type is not Optional

        Example:
            >>> from typing import Optional
            >>> ParameterTypeUtils.get_optional_inner_type(Optional[str])
            <class 'str'>
        """
        optional_type = optional_member_type(param_type)
        if optional_type is None:
            raise ValueError(f"Type {param_type} is not Optional")
        return optional_type

    @staticmethod
    def is_enum_type(param_type: type) -> bool:
        """
        Check if a type is an Enum type.

        Args:
            param_type: The type to check

        Returns:
            True if the type is an Enum, False otherwise
        """
        return annotation_is_enum_type(param_type)

    @staticmethod
    def is_list_of_enums(param_type: type) -> bool:
        """
        Check if parameter type is List[Enum].

        Args:
            param_type: The type to check

        Returns:
            True if the type is List[Enum], False otherwise
        """
        return annotation_is_list_of_enums(param_type)

    @staticmethod
    def get_enum_from_list_type(param_type: type) -> type | None:
        """
        Extract enum type from List[Enum] type.

        Args:
            param_type: The List[Enum] type

        Returns:
            The Enum type, or None if not a List[Enum]
        """
        return get_enum_from_list(param_type)

    @staticmethod
    def has_dataclass_fields(obj: any) -> bool:
        """
        Check if an object has dataclass fields.

        Args:
            obj: The object to check

        Returns:
            True if the object has __dataclass_fields__ attribute
        """
        return DataclassFieldAccess.is_config_type(obj if isinstance(obj, type) else type(obj))

    @staticmethod
    def has_resolve_field_value(obj: any) -> bool:
        """
        Check if an object has the _resolve_field_value method (lazy dataclass).

        Args:
            obj: The object to check

        Returns:
            True if the object has _resolve_field_value attribute
        """
        return isinstance(obj, LazyDataclass)

    @staticmethod
    def is_concrete_dataclass(obj: any) -> bool:
        """
        Check if an object is a concrete (non-lazy) dataclass.

        Args:
            obj: The object to check

        Returns:
            True if the object is a concrete dataclass
        """
        return ParameterTypeUtils.has_dataclass_fields(
            obj
        ) and not ParameterTypeUtils.has_resolve_field_value(obj)

    @staticmethod
    def is_lazy_dataclass(obj: any) -> bool:
        """
        Check if an object is a lazy dataclass.

        Args:
            obj: The object to check

        Returns:
            True if the object is a lazy dataclass
        """
        return ParameterTypeUtils.has_resolve_field_value(obj)

    @staticmethod
    def extract_value_attribute(obj: any) -> any:
        """
        Extract the value attribute from an object if it exists.

        This is commonly used for enum values and other wrapped types.

        Args:
            obj: The object to extract value from

        Returns:
            The value attribute if it exists, otherwise the original object
        """
        return obj.value if isinstance(obj, Enum) else obj

    @staticmethod
    def convert_string_to_bool(value: str) -> bool:
        """
        Convert string to boolean using standard true/false patterns.

        Args:
            value: The string value to convert

        Returns:
            True if the string represents a true value, False otherwise
        """
        return value.lower() in CONSTANTS.TRUE_STRINGS
