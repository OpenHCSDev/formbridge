"""Base configuration class for form generation.

Provides hooks for applications to customize form generation behavior.
"""

from dataclasses import dataclass, field
from typing import Any


@dataclass
class FormGenConfig:
    """Base configuration for form generation behavior.

    Applications can subclass this to provide custom configuration.

    Attributes:
        enable_placeholder_styling: Whether to apply special styling to placeholder values
        enable_help_buttons: Whether to show help buttons for fields with docstrings
        enable_inheritance_tracking: Whether to show inheritance source indicators
        custom_widget_factories: Custom widget factories by type
    """

    enable_placeholder_styling: bool = True
    enable_help_buttons: bool = True
    enable_inheritance_tracking: bool = True
    custom_widget_factories: dict[type, Any] = field(default_factory=dict)
    jedi_project_paths: list[str] = field(default_factory=list)
    log_dir: str | None = None
    log_prefixes: list[str] = field(default_factory=lambda: ["formbridge_"])
    log_root_logger_name: str | None = None
    performance_logger_name: str = "formbridge.performance"
    performance_log_filename: str = "performance.log"
    path_cache_file: str | None = None
    external_editor_env_var: str = "PYQT_REACTIVE_USE_EXTERNAL_EDITOR"
    """Environment variable that, set to 1/true/yes, edits code in an external editor."""


# Global config instance (set by application)
_form_config: FormGenConfig | None = None


def set_form_config(config: FormGenConfig) -> None:
    """Set the global form generation configuration.

    Args:
        config: FormGenConfig instance
    """
    global _form_config
    _form_config = config


def get_form_config() -> FormGenConfig:
    """Get the current form generation configuration.

    Returns:
        Current FormGenConfig or default if not set
    """
    if _form_config is None:
        return FormGenConfig()
    return _form_config
