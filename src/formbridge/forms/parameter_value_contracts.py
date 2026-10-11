"""Nominal contracts for dynamic form parameter payloads."""

from __future__ import annotations

from abc import ABC
from collections.abc import Callable


class ParameterValue(ABC):
    """Nominal annotation for values carried by parameter forms."""


class WidgetValue(ParameterValue):
    """Nominal annotation for values received from PyQt widgets."""


class FormObject(ABC):
    """Nominal annotation for objects analyzed by the form layer."""


class FormContext(ABC):
    """Nominal annotation for context objects used by placeholder resolution."""


class ParameterDefaultsByName(dict):
    """Map of parameter name to extracted/default value."""


class ParameterTypesByName(dict):
    """Map of parameter name to type annotation."""


class NestedManagerMap(dict):
    """Map of nested field name to nested form manager."""


class ParameterDescriptionByPath(dict):
    """Map of dotted parameter path to rendered description."""


class GeneratedServiceNamespace(dict):
    """Module namespace populated with generated initialization services."""


class ParameterInfoSequence(list):
    """Ordered parameter information sequence for widget build orchestration."""


ParameterDescriptionProvider = Callable[[], ParameterDescriptionByPath]
