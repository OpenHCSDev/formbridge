"""Nominal identity contract for typed Qt tree payloads."""

from abc import ABC, abstractmethod


class TreeItemKeyProviderABC(ABC):
    """Payload that owns its stable tree-state identity."""

    @abstractmethod
    def tree_item_key(self) -> str:
        """Return the stable key segment for this payload."""
        raise NotImplementedError


class EndpointPortProviderABC(TreeItemKeyProviderABC):
    """Typed endpoint payload whose port is also its stable tree identity."""

    @property
    @abstractmethod
    def port(self) -> int:
        """Return the endpoint port represented by this payload."""
        raise NotImplementedError

    def tree_item_key(self) -> str:
        """Derive stable tree identity from the declared endpoint port."""
        return f"port:{self.port}"
