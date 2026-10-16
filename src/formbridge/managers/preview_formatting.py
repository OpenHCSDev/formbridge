"""Preview field formatting for manager list items."""

from objectstate.declarations import ValueDeclaration
from formbridge.protocols.preview_formatter import PreviewFormatterRegistry

from formbridge.utils.preview_formatters import (
    PreviewFieldFormatRequest,
    check_enabled_field,
    resolve_field_abbreviation,
    resolve_preview_label,
)


class ManagerPreviewFieldFormatter:
    """Formats field values for AbstractManagerWidget preview segments."""

    def format_field(self, request: PreviewFieldFormatRequest) -> str | None:
        """Format a value using metadata from its actual declaring type."""
        declaration = ValueDeclaration.of(request.field_owner).owner_scope.field_types[request.field_name]
        return declaration.admit(request.value).render_preview(self, request)

    def scalar_preview(self, request):
        if request.value is None:
            return None
        formatted = request.value_formatter(request.value)
        if formatted is None:
            return None
        abbreviation = resolve_field_abbreviation(
            request.field_owner,
            request.field_name,
        )
        abbrev = abbreviation.abbreviation if abbreviation is not None else request.field_name
        return f"{abbrev}:{formatted}"

    def configuration_preview(self, request: PreviewFieldFormatRequest) -> str | None:
        formatted = PreviewFormatterRegistry.format_field(request.value, request.field_name)
        if formatted is None:
            formatted = self._preview_label_for_config(request.value)
        return formatted

    def _preview_label_for_config(self, config_obj: object) -> str | None:
        if not check_enabled_field(config_obj):
            return None
        resolution = resolve_preview_label(config_obj)
        return resolution.label if resolution is not None else None
