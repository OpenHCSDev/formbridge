"""Which keys click hints get, one fixed-width sequence per target in target order, and
which part of its key a hint label shows."""
from __future__ import annotations

from abc import ABC, abstractmethod


class HintKeyAssignment:
    """Hint keys come from the home-row-first alphabet; every key has the width the target
    count needs, so typing a prefix narrows the targets without one key shadowing another."""

    alphabet = "asdfghjklqwertyuiopzxcvbnm"

    @classmethod
    def label_width(cls, count: int) -> int:
        width = 1
        while len(cls.alphabet) ** width < count:
            width += 1
        return width

    @classmethod
    def label(cls, index, width):
        characters = []
        for _ in range(width):
            index, digit = divmod(index, len(cls.alphabet))
            characters.append(cls.alphabet[digit])
        return "".join(reversed(characters))


class HintLabelStyle(ABC):
    """Which part of a hint's assigned key its label shows. Presentation never changes the
    key or its original activation."""

    @classmethod
    @abstractmethod
    def shown(cls, key: str, prefix: str) -> tuple[str, int]:
        """The label's text, and how many of its leading characters are already typed."""


class NextLetterHints(HintLabelStyle):
    """Show the next untyped letter at the target."""

    @classmethod
    def shown(cls, key: str, prefix: str) -> tuple[str, int]:
        return key[len(prefix):len(prefix) + 1], 0


class FullKeyHints(HintLabelStyle):
    """Show the complete assigned sequence, including the typed prefix."""

    @classmethod
    def shown(cls, key: str, prefix: str) -> tuple[str, int]:
        return key, len(prefix)
