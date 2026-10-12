"""Lightweight metadata keys shared by function-pattern tooling."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any, ClassVar


class PatternScopeToken:
    """Nominal owner for UI-only function-pattern scope-token metadata."""

    key: ClassVar[str] = "__formbridge_scope_token__"

    @classmethod
    def key_name(cls) -> str:
        return cls.key

    @classmethod
    def key_in(cls, values: Mapping[Any, Any]) -> bool:
        return cls.key_name() in values

    @classmethod
    def is_key(cls, key: Any) -> bool:
        return key == cls.key_name()

    @classmethod
    def without_token(cls, values: Mapping[Any, Any]) -> dict[Any, Any]:
        return {key: value for key, value in values.items() if not cls.is_key(key)}
