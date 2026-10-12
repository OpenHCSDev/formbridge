"""
Configuration for parameter form managers.
"""

from dataclasses import dataclass
from typing import Any

from formbridge.forms.parameter_form_constants import CONSTANTS


@dataclass
class ParameterFormConfig:
    """
    Configuration for parameter form managers.

    This dataclass encapsulates all configuration options for parameter form
    managers, providing a clean interface for customizing form behavior.

    Attributes:
        field_id: Unique identifier for the form
        parameter_info: Optional parameter information dictionary
        is_global_config_editing: Whether editing global configuration
        global_config_type: Type of global configuration being edited
        placeholder_prefix: Prefix for placeholder text
        use_scroll_area: Whether to use scroll area (PyQt only)
        enable_debug: Whether to enable debug logging
        debug_target_params: Set of parameters to debug
        framework: UI framework ('pyqt6' or 'textual')
        color_scheme: Optional color scheme for PyQt
        function_target: Optional function target for docstring fallback
    """

    field_id: str
    parameter_info: dict | None = None
    is_global_config_editing: bool = False
    global_config_type: type | None = None
    placeholder_prefix: str = CONSTANTS.DEFAULT_PLACEHOLDER_PREFIX
    use_scroll_area: bool | None = None
    enable_debug: bool = False
    debug_target_params: set | None = None
    framework: str = CONSTANTS.TEXTUAL_FRAMEWORK
    color_scheme: Any | None = None
    function_target: Any | None = None

    def with_debug(
        self, enabled: bool = True, target_params: set | None = None
    ) -> "ParameterFormConfig":
        """Return a copy with debug settings configured."""
        import copy

        config = copy.deepcopy(self)
        config.enable_debug = enabled
        if target_params is not None:
            config.debug_target_params = target_params
        return config

    def with_global_config(
        self, global_config_type: type, editing: bool = True
    ) -> "ParameterFormConfig":
        """Return a copy with global configuration settings."""
        import copy

        config = copy.deepcopy(self)
        config.is_global_config_editing = editing
        config.global_config_type = global_config_type
        return config
