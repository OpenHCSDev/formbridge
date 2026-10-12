"""Nominal mechanics shared by executable UI action declarations."""

from __future__ import annotations

from collections.abc import Callable
from typing import Self, cast


class LabeledExecutableActionMixin:
    """Construct and invoke labelled string-enum actions through one owner."""

    _value_: str
    label: str
    _executor: Callable[..., None]

    @classmethod
    def _new_member(
        cls,
        value: str,
        label: str,
        executor: Callable[..., None],
    ) -> Self:
        member = cast(Self, str.__new__(cast(type[str], cls), value))
        member._value_ = value
        member.label = label
        member._executor = executor
        return member

    def invoke(self, target: object) -> None:
        """Invoke this member's declared execution leaf for its owning target."""

        self._executor(target)
