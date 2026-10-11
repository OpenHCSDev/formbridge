"""Status presentation strategy abstractions."""
from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import Any, Optional


@dataclass(frozen=True)
class StatusPresentationInput:
    """Typed input for status text presentation."""

    message: str
    context: Any = None


@dataclass(frozen=True)
class StatusPresentationResult:
    """Rendered output from a status presentation strategy."""

    text: str
    color_hex: Optional[str] = None


class StatusPresentationStrategyABC(ABC):
    """Abstract strategy for manager status text presentation."""

    @abstractmethod
    def present(self, status_input: StatusPresentationInput) -> StatusPresentationResult:
        """Render status presentation output."""


class DefaultStatusPresentationStrategy(StatusPresentationStrategyABC):
    """Default passthrough status presentation implementation."""

    def present(self, status_input: StatusPresentationInput) -> StatusPresentationResult:
        return StatusPresentationResult(text=status_input.message, color_hex=None)
