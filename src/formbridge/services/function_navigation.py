"""Typed helpers for function-pattern field and navigation payloads."""

from __future__ import annotations

from dataclasses import dataclass
from typing import ClassVar, Mapping, Optional

from objectstate import DottedFieldPath


class FunctionPatternField:
    """Nominal owner for function-pattern parent-field semantics."""

    name: ClassVar[str] = "func"
    token_field_prefix: ClassVar[str] = "func.token:"
    target_delimiter: ClassVar[str] = "|"

    @classmethod
    def parameter_name(cls) -> str:
        return cls.name

    @classmethod
    def parameter_in(cls, values: Mapping[str, object]) -> bool:
        return cls.parameter_name() in values

    @classmethod
    def value_from(cls, values: Mapping[str, object]) -> object:
        return values[cls.parameter_name()]

    @classmethod
    def scope_token_prefix(cls) -> str:
        return cls.parameter_name()

    @classmethod
    def owns_field_path(cls, field_path: str | None) -> bool:
        """Return whether a field path belongs to the function-pattern field."""

        if not isinstance(field_path, str):
            return False
        return (
            DottedFieldPath(cls.parameter_name()).contains_path(field_path)
            or field_path.startswith(cls.token_field_prefix)
        )


FUNCTION_FIELD_ROOT = FunctionPatternField.parameter_name()
FUNCTION_TOKEN_FIELD_PREFIX = FunctionPatternField.token_field_prefix
FUNCTION_TARGET_DELIMITER = FunctionPatternField.target_delimiter


@dataclass(frozen=True)
class FunctionFieldTarget:
    """Parsed function navigation target."""

    token: Optional[str]
    index: Optional[int]
    base_field_path: str


def is_function_field_path(field_path: str | None) -> bool:
    """Return True when the field path targets function-pattern UI."""
    return FunctionPatternField.owns_field_path(field_path)


def build_function_token_field_path(
    token: str,
    fallback_base_field_path: str = FUNCTION_FIELD_ROOT,
) -> str:
    """Build a token-scoped function field path payload."""
    normalized_token = token.strip()
    if not normalized_token:
        raise ValueError("Function token must be non-empty.")
    normalized_base = fallback_base_field_path.strip() or FunctionPatternField.parameter_name()
    return (
        f"{FunctionPatternField.token_field_prefix}{normalized_token}"
        f"{FunctionPatternField.target_delimiter}{normalized_base}"
    )


def parse_function_field_target(field_path: str) -> FunctionFieldTarget:
    """Parse function field path into token/index/base components."""
    normalized = field_path.strip()
    token: Optional[str] = None

    if normalized.startswith(FunctionPatternField.token_field_prefix):
        payload = normalized[len(FunctionPatternField.token_field_prefix) :]
        if FunctionPatternField.target_delimiter in payload:
            token_part, remainder = payload.split(
                FunctionPatternField.target_delimiter,
                1,
            )
            token = token_part.strip() or None
            normalized = remainder.strip() or FunctionPatternField.parameter_name()
        else:
            token = payload.strip() or None
            normalized = FunctionPatternField.parameter_name()

    index: Optional[int] = None
    rest = normalized
    if rest.startswith(FunctionPatternField.parameter_name()):
        rest = rest[len(FunctionPatternField.parameter_name()) :]

    if rest.startswith("["):
        close = rest.find("]")
        if close > 1:
            digits = rest[1:close]
            if digits.isdigit():
                index = int(digits)
    elif rest.startswith("."):
        parts = rest[1:].split(".", 1)
        if parts and parts[0].isdigit():
            index = int(parts[0])

    return FunctionFieldTarget(
        token=token,
        index=index,
        base_field_path=normalized,
    )
