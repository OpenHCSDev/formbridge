"""Apply code-editor fields through admitted handles and the existing mutation owner."""

from __future__ import annotations

from typing import Any

from objectstate.construction_binding import admit_target


class CodeEditorFormUpdater:
    @staticmethod
    def update_form_from_instance(form_manager, new_instance: Any, broadcast_callback=None) -> None:
        source = admit_target(new_instance)
        for field in form_manager.fields.children:
            member = source.read_raw(field.name)
            if member != field.raw_member:
                form_manager.update_parameter(field.name, member.stored)
        if broadcast_callback is not None:
            broadcast_callback(new_instance)
