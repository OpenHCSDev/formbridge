"""
Pattern Data Manager - Pure data operations for function patterns.

This service handles pattern data structure operations and transformations
with order determinism and immutable operations.

Framework-agnostic - can be used by any UI framework (PyQt, Textual, etc.).
"""

import copy
from collections.abc import Callable, Mapping
from typing import NewType

from objectstate.object_state_metadata import (
    ObjectStateMetadataContract,
    ObjectStateMetadataContractRegistry,
)

PatternKey = NewType("PatternKey", str)


# Internal metadata key stored in kwargs for per-entry identity.
# This is used by the PyQt/ObjectState integration to create stable, per-occurrence
# scopes for duplicate functions in patterns.

# Namespaced metadata keys for ObjectState.metadata
FUNC_EDITOR_SELECTED_PATTERN_KEY_META_KEY = "formbridge.func_editor.selected_pattern_key"
FUNC_EDITOR_PATTERN_TOKENS_META_KEY = "formbridge.func_editor.pattern_tokens"

ObjectStateMetadataContractRegistry.register(
    ObjectStateMetadataContract(
        key=FUNC_EDITOR_SELECTED_PATTERN_KEY_META_KEY,
        owner="formbridge.function_editor",
        description="Currently selected dict-pattern key for function editor time travel.",
    )
)
ObjectStateMetadataContractRegistry.register(
    ObjectStateMetadataContract(
        key=FUNC_EDITOR_PATTERN_TOKENS_META_KEY,
        owner="formbridge.function_editor",
        description="Stable child ObjectState scope tokens for function pattern entries.",
    )
)


class PatternDataManager:
    """
    Pure data operations for function patterns.

    Handles List↔Dict conversions, cloning, and data transformations
    with order determinism and immutable operations.
    """

    @staticmethod
    def clone_pattern(pattern: list | dict) -> list | dict:
        """
        Deep clone preserving callable references exactly.

        Args:
            pattern: Pattern to clone (List or Dict)

        Returns:
            Deep cloned pattern with preserved callable references
        """
        if pattern is None:
            return []
        return copy.deepcopy(pattern)

    @staticmethod
    def convert_list_to_dict(pattern: list) -> dict:
        """
        Convert List pattern to empty Dict - user must add component keys manually.

        Args:
            pattern: List pattern to convert (will be discarded)

        Returns:
            Empty dict for user to populate with experimental component identifiers
        """
        if not isinstance(pattern, list):
            raise ValueError(f"Expected list, got {type(pattern)}")

        # Return empty dict - user will add experimental component keys manually
        return {}

    @staticmethod
    def convert_dict_to_list(pattern: dict) -> list | dict:
        """
        Convert Dict pattern to List when empty.

        Args:
            pattern: Dict pattern to potentially convert

        Returns:
            Empty list if dict is empty, otherwise returns original dict
        """
        if not isinstance(pattern, dict):
            raise ValueError(f"Expected dict, got {type(pattern)}")

        # Convert to empty list if dict is empty
        if not pattern:
            return []

        # Keep as dict if it has keys
        return pattern

    @staticmethod
    def extract_func_and_kwargs(func_item) -> tuple[Callable, dict]:
        """Return ``(callable, kwargs)`` for a ``(callable, kwargs)`` tuple or a bare callable.

        Raises:
            TypeError: for any other item, so a malformed entry is never dropped silently.
        """
        if isinstance(func_item, tuple) and len(func_item) == 2 and callable(func_item[0]):
            func, kwargs = func_item
            if not isinstance(kwargs, Mapping):
                raise TypeError("Function-pattern tuple entries must carry a kwargs mapping.")
            return func, dict(kwargs)
        if callable(func_item):
            return func_item, {}
        raise TypeError(
            "Function-pattern entries are callables or (callable, kwargs) pairs, "
            f"got {func_item!r}."
        )

    @staticmethod
    def validate_pattern_structure(pattern: list | dict) -> bool:
        """
        Basic structural validation of pattern.

        Args:
            pattern: Pattern to validate

        Returns:
            True if structure is valid, False otherwise
        """
        if pattern is None:
            return True

        if isinstance(pattern, list):
            # Validate list items are callables or (callable, dict) tuples
            for item in pattern:
                try:
                    PatternDataManager.extract_func_and_kwargs(item)
                except TypeError:
                    return False
            return True

        elif isinstance(pattern, dict):
            # Validate dict values are lists of callables
            for key, value in pattern.items():
                if not isinstance(value, list):
                    return False
                # Recursively validate the list
                if not PatternDataManager.validate_pattern_structure(value):
                    return False
            return True

        else:
            return False

    @staticmethod
    def get_current_functions(pattern: list | dict, key: PatternKey, is_dict: bool) -> list:
        """
        Extract function list for current context.

        Args:
            pattern: Full pattern (List or Dict)
            key: Current key (for Dict patterns)
            is_dict: Whether pattern is currently in dict mode

        Returns:
            List of functions for current context
        """
        if is_dict and isinstance(pattern, dict):
            if key in pattern:
                return pattern[key]
            return []
        elif not is_dict and isinstance(pattern, list):
            return pattern
        else:
            return []

    @staticmethod
    def update_pattern_functions(
        pattern: list | dict, key: PatternKey, is_dict: bool, new_functions: list
    ) -> list | dict:
        """
        Update functions in pattern for current context.

        Returns new pattern object (immutable operation).

        Args:
            pattern: Original pattern
            key: Current key (for Dict patterns)
            is_dict: Whether pattern is in dict mode
            new_functions: New function list

        Returns:
            New pattern with updated functions
        """
        if is_dict and isinstance(pattern, dict):
            new_pattern = copy.deepcopy(pattern)
            new_pattern[key] = new_functions
            return new_pattern
        elif not is_dict and isinstance(pattern, list):
            return copy.deepcopy(new_functions)
        else:
            # Fallback - return original pattern
            return copy.deepcopy(pattern)

    @staticmethod
    def add_new_key(pattern: dict, new_key: str) -> dict:
        """
        Add new key to dict pattern.

        Args:
            pattern: Dict pattern
            new_key: Key to add

        Returns:
            New dict with added key
        """
        new_pattern = copy.deepcopy(pattern)
        if new_key not in new_pattern:
            new_pattern[new_key] = []
        return new_pattern

    @staticmethod
    def remove_key(pattern: dict, key_to_remove: PatternKey) -> list | dict:
        """
        Remove key from dict pattern.

        If dict becomes empty after removal, converts back to list.

        Args:
            pattern: Dict pattern
            key_to_remove: Key to remove

        Returns:
            New pattern (List if dict becomes empty, Dict otherwise)
        """
        new_pattern = copy.deepcopy(pattern)
        if key_to_remove in new_pattern:
            del new_pattern[key_to_remove]

        # Check if should convert back to list (when empty)
        return PatternDataManager.convert_dict_to_list(new_pattern)
