"""Apply raw code-editor values through the form's existing mutation owner."""

from __future__ import annotations

from dataclasses import fields
from typing import Any

from objectstate import Unset, semantic_values_equal
from objectstate.field_access import DataclassFieldAccess


class CodeEditorFormUpdater:
    """Update concrete configurations without resolving their stored meanings."""

    @staticmethod
    def update_form_from_instance(form_manager, new_instance: Any, broadcast_callback=None) -> None:
        is_configuration = DataclassFieldAccess.is_container(new_instance)
        names = (
            tuple(item.name for item in fields(new_instance))
            if is_configuration else tuple(form_manager.parameters)
        )
        for name in names:
            if name not in form_manager.parameters:
                continue
            value = (
                DataclassFieldAccess.raw_value(new_instance, name)
                if is_configuration else getattr(new_instance, name, Unset())
            )
            if DataclassFieldAccess.is_container(value):
                CodeEditorFormUpdater._update_nested_dataclass(form_manager, name, value)
            else:
                CodeEditorFormUpdater._update_parameter_if_changed(form_manager, name, value)
        if broadcast_callback:
            broadcast_callback(new_instance)

    @staticmethod
    def _update_nested_dataclass(manager, field_name: str, new_value: Any) -> None:
        """One recursive path owns both first-level and deeper configurations."""
        nested = manager.nested_managers.get(field_name)
        if nested is None:
            CodeEditorFormUpdater._update_parameter_if_changed(manager, field_name, new_value)
            return
        for item in fields(new_value):
            if item.name not in nested.parameters:
                continue
            value = DataclassFieldAccess.raw_value(new_value, item.name)
            if DataclassFieldAccess.is_container(value):
                CodeEditorFormUpdater._update_nested_dataclass(nested, item.name, value)
            else:
                CodeEditorFormUpdater._update_parameter_if_changed(nested, item.name, value)

    @staticmethod
    def _update_parameter_if_changed(form_manager, field_name: str, new_value: Any) -> bool:
        """Avoid dispatching unchanged fields of a reconstructed code document."""
        parameters = form_manager.parameters
        if field_name not in parameters or semantic_values_equal(parameters[field_name], new_value):
            return False
        form_manager.update_parameter(field_name, new_value)
        return True
