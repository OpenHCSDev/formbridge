"""What activating a control means, independent of how a toolkit finds the click target."""
from __future__ import annotations

from abc import abstractmethod
from collections.abc import Callable


class PrimaryEffect:
    """A control declares its primary effect: what a click, a hint key or an activate key runs."""

    @property
    @abstractmethod
    def primary_activation(self) -> Callable[[], object]: ...


class ContextEffect:
    """A control declares its contextual effect at the offset where it was activated."""

    @abstractmethod
    def context_activation(self, offset) -> None: ...
