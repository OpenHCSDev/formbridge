"""Nominal host contracts for component and function selection."""

from abc import ABC, abstractmethod
from collections.abc import Callable, Iterable
from typing import Any


class ComponentSelectionProviderABC(ABC):
    """Host-owned component discovery and selection behavior."""

    @abstractmethod
    def is_grouped(self, group_by: Any) -> bool:
        """Return whether ``group_by`` names a grouping (not absent or ungrouped)."""
        raise NotImplementedError

    @abstractmethod
    def grouping_label(self, group_by: Any) -> str:
        """Return the display label of a grouping value."""
        raise NotImplementedError

    @abstractmethod
    def grouping_overlaps_variable_components(
        self,
        group_by: Any,
        variable_components: Iterable[Any],
    ) -> bool:
        """Return whether the grouping is also one of the variable components."""
        raise NotImplementedError

    @abstractmethod
    def get_component_keys(self, group_by: Any) -> list[str]:
        """Return available component keys for a given group_by."""
        raise NotImplementedError

    @abstractmethod
    def has_components_available(self, group_by: Any) -> bool:
        """Check if components are available for the given group_by without fetching them all.

        Used to determine if UI elements (like component selection buttons) should be enabled.
        Should return False if the underlying data source (e.g., orchestrator) is not ready.
        """
        raise NotImplementedError

    @abstractmethod
    def get_component_display_name(
        self,
        group_by: Any,
        component_key: str,
    ) -> str | None:
        """Return a human-readable name for a component key."""
        raise NotImplementedError

    @abstractmethod
    def select_components(
        self,
        available_components: Iterable[str],
        selected_components: Iterable[str],
        group_by: Any,
        parent: Any | None = None,
        **context: Any,
    ) -> list[str] | None:
        """Show selection UI and return chosen components (or None if canceled)."""
        raise NotImplementedError


class FunctionSelectionProviderABC(ABC):
    """Host-owned function selection behavior."""

    @abstractmethod
    def select_function(
        self,
        parent: Any | None = None,
        **context: Any,
    ) -> Callable | None:
        """Return a selected function or None."""
        raise NotImplementedError


_component_selection_provider: ComponentSelectionProviderABC | None = None
_function_selection_provider: FunctionSelectionProviderABC | None = None


def register_component_selection_provider(
    provider: ComponentSelectionProviderABC,
) -> None:
    """Register a global component selection provider."""
    if not isinstance(provider, ComponentSelectionProviderABC):
        raise TypeError(
            "Component selection providers must inherit " "ComponentSelectionProviderABC."
        )
    global _component_selection_provider
    _component_selection_provider = provider


def get_component_selection_provider() -> ComponentSelectionProviderABC | None:
    """Get the registered component selection provider."""
    return _component_selection_provider


def register_function_selection_provider(
    provider: FunctionSelectionProviderABC,
) -> None:
    """Register a global function selection provider."""
    if not isinstance(provider, FunctionSelectionProviderABC):
        raise TypeError(
            "Function selection providers must inherit " "FunctionSelectionProviderABC."
        )
    global _function_selection_provider
    _function_selection_provider = provider


def get_function_selection_provider() -> FunctionSelectionProviderABC | None:
    """Get the registered function selection provider."""
    return _function_selection_provider
