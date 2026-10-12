"""Generic code-document capability for WindowManager-managed windows."""

from __future__ import annotations

import hashlib
import os
from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import Generic, TypeVar

from formbridge.protocols.codegen_provider import get_codegen_provider
from formbridge.protocols.form_config import get_form_config

PYTHON_MIME_TYPE = "text/x-python"
EXTERNAL_EDITOR_ENABLED_VALUES = frozenset(("1", "true", "yes"))
DeclarationT = TypeVar("DeclarationT")


class WindowCodeDocumentError(RuntimeError):
    """Raised when a managed window cannot service a code-document request."""


@dataclass(frozen=True, slots=True)
class WindowCodeDocument(Generic[DeclarationT]):
    """Rendered code document owned by one managed window."""

    title: str
    source: str
    mime_type: str = PYTHON_MIME_TYPE
    declaration_type: type[DeclarationT] | None = None


class WindowCodeDocumentDriver(ABC, Generic[DeclarationT]):
    """Read/apply code-mode content for one WindowManager scope."""

    def current_revision_token(self) -> str:
        """Return the revision of the authoritative clean document content."""
        source = self.read_document(clean=True).source
        return hashlib.sha256(source.encode("utf-8")).hexdigest()

    def records_object_state_snapshot_on_apply(self) -> bool:
        """Return whether applying this document must advance ObjectState history."""
        return True

    def writable(self) -> bool:
        """Return whether the live document currently accepts mutations."""
        return True

    def source_is_current(
        self,
        source: str,
        *,
        current_document: WindowCodeDocument[DeclarationT] | None = None,
    ) -> bool:
        """Compare edited source through the nominal declaration normalizer."""
        current = current_document or self.read_document(clean=True)
        provider = get_codegen_provider()
        if provider is None or current.declaration_type is None:
            return current.source == source
        try:
            normalized = provider.normalize_source(
                source,
                declaration_type=current.declaration_type,
                clean_mode=True,
            )
        except Exception:
            return current.source == source
        return current.source == normalized

    @abstractmethod
    def read_document(self, clean: bool = True) -> WindowCodeDocument[DeclarationT]:
        """Return the current code document."""
        raise NotImplementedError

    @abstractmethod
    def validate_source(self, source: str) -> None:
        """Validate source without changing UI state."""
        raise NotImplementedError

    @abstractmethod
    def apply_source(self, source: str) -> None:
        """Apply source through the same state path as interactive code mode."""
        raise NotImplementedError


def use_external_code_editor() -> bool:
    """Whether code documents open in an external editor (the host's environment switch)."""

    value = os.environ.get(get_form_config().external_editor_env_var, "")
    return value.lower() in EXTERNAL_EDITOR_ENABLED_VALUES
