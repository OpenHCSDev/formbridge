"""Host registrations for application-specific config preview formatting."""

from collections.abc import Callable
from typing import TypeAlias

# Type alias for formatter functions
# Takes (config_instance, field_name) -> formatted_string
PreviewFormatter: TypeAlias = Callable[[object, str], str | None]


class PreviewFormatterRegistry:
    """Registry for preview formatters by config type.

    Applications can register formatters for specific config types to customize
    how fields are displayed in list item previews.

    Example:
        from formbridge.protocols.preview_formatter import PreviewFormatterRegistry

        def format_zarr_config(config, field_name):
            if field_name == 'compression':
                return f"comp={config.compression[:3]}"  # Abbreviate
            return str(getattr(config, field_name))

        PreviewFormatterRegistry.register(ZarrConfig, format_zarr_config)
    """

    _formatters: dict[type[object], PreviewFormatter] = {}

    @classmethod
    def register(
        cls,
        config_type: type[object],
        formatter: PreviewFormatter,
    ) -> None:
        """Register a formatter for a config type.

        Args:
            config_type: Config class to format
            formatter: Formatter function taking (config, field_name) -> str
        """
        cls._formatters[config_type] = formatter

    @classmethod
    def get_formatter(cls, config_type: type[object]) -> PreviewFormatter | None:
        """Get formatter for a config type.

        Args:
            config_type: Config class

        Returns:
            Formatter function if registered, None otherwise
        """
        from formbridge.utils.preview_formatters import canonical_declaration_mro

        for declaration_type in canonical_declaration_mro(config_type):
            formatter = cls._formatters.get(declaration_type)
            if formatter is not None:
                return formatter

        return None

    @classmethod
    def format_field(cls, config: object, field_name: str) -> str | None:
        """Format a field using registered formatter if available.

        Args:
            config: Config instance
            field_name: Field name to format

        Returns:
            Formatted string if formatter available, None otherwise
        """
        formatter = cls.get_formatter(type(config))
        if formatter is None:
            return None
        return formatter(config, field_name)


# Convenience function for registration
def register_preview_formatter(
    config_type: type[object],
    formatter: PreviewFormatter,
) -> None:
    """Register a preview formatter for a config type.

    Args:
        config_type: Config class
        formatter: Formatter function
    """
    PreviewFormatterRegistry.register(config_type, formatter)
