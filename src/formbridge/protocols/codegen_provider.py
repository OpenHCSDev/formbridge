"""Nominal code-generation contract for app-specific code emitters."""

from abc import ABC, abstractmethod
from typing import TypeVar

DeclarationT = TypeVar("DeclarationT")


class CodegenProviderABC(ABC):
    """Host code-generation behavior consumed by generic code editors."""

    @abstractmethod
    def render_assignment(
        self,
        value: object,
        *,
        assignment_name: str,
        header: str,
        clean_mode: bool,
    ) -> str:
        """Render one named value as editable source."""
        raise NotImplementedError

    @abstractmethod
    def normalize_source(
        self,
        source: str,
        *,
        declaration_type: type[DeclarationT],
        clean_mode: bool,
    ) -> str:
        """Normalize source through the declaration authority being edited."""
        raise NotImplementedError


_codegen_provider: CodegenProviderABC | None = None


def register_codegen_provider(provider: CodegenProviderABC) -> None:
    """Register a global code generation provider."""
    if not isinstance(provider, CodegenProviderABC):
        raise TypeError("Code-generation providers must inherit CodegenProviderABC.")
    global _codegen_provider
    _codegen_provider = provider


def get_codegen_provider() -> CodegenProviderABC | None:
    """Get the registered code generation provider."""
    return _codegen_provider
