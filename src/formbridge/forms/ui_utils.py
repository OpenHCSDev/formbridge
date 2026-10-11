"""
UI utilities for pyqt-reactor.

Simple formatting and debug utilities used across the forms layer.
"""

import logging
from dataclasses import dataclass
from enum import Enum
from typing import Any


@dataclass(frozen=True)
class FieldDisplayText:
    """Canonical display strings derived from a parameter field name."""

    display_name: str
    field_label: str
    checkbox_label: str
    group_title: str

    @classmethod
    def from_field_name(cls, name: str) -> "FieldDisplayText":
        display_name = name.replace('_', ' ').title()
        return cls(
            display_name=display_name,
            field_label=f"{display_name}:",
            checkbox_label=f"Enable {display_name}",
            group_title=display_name,
        )


def format_field_id(parent: str, param: str) -> str:
    """Generate field ID: 'parent', 'param' -> 'parent_param'"""
    return f"{parent}_{param}"


def debug_param(param_name: str, value: Any, context: str = "") -> None:
    """Simple parameter debug logging"""
    context_str = f" [{context}]" if context else ""
    logging.debug(f"PARAM: {param_name} = {value}{context_str}")


def format_enum_display(enum_value: Enum) -> str:
    """Get enum display text, including nested enum-valued members."""
    if isinstance(enum_value.value, Enum):
        return str(enum_value.value.value)
    if isinstance(enum_value.value, str):
        return enum_value.value
    return enum_value.name.upper()


def format_enum_placeholder(enum_value: Enum, prefix: str = "Pipeline default: ") -> str:
    """Get enum placeholder: Enum.VALUE -> 'Pipeline default: VALUE'"""
    return f"{prefix}{format_enum_display(enum_value)}"
