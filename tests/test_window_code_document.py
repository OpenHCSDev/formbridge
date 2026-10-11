"""Document-local revision ownership for managed window code documents."""

from __future__ import annotations

import pytest

from formbridge.protocols.codegen_provider import CodegenProviderABC
from formbridge.protocols import codegen_provider
from formbridge.services.window_code_document import WindowCodeDocument, WindowCodeDocumentDriver


class MutableCodeDocumentDriver(WindowCodeDocumentDriver):
    def __init__(self, source: str) -> None:
        self.source = source

    def read_document(self, clean: bool = True) -> WindowCodeDocument:
        del clean
        return WindowCodeDocument(title="Mutable document", source=self.source)

    def validate_source(self, source: str) -> None:
        if source == "invalid":
            raise ValueError("invalid source")

    def apply_source(self, source: str) -> None:
        self.validate_source(source)
        self.source = source


def test_default_revision_tracks_document_content_not_rejected_validation() -> None:
    driver = MutableCodeDocumentDriver("original")
    original_revision = driver.current_revision_token()

    assert driver.writable()
    with pytest.raises(ValueError, match="invalid source"):
        driver.validate_source("invalid")

    assert driver.current_revision_token() == original_revision
    driver.apply_source("replacement")
    assert driver.current_revision_token() != original_revision


def test_declaration_backed_source_comparison_uses_codegen_normalization(
    monkeypatch,
) -> None:
    class NormalizingCodegenProvider(CodegenProviderABC):
        def render_assignment(
            self,
            value: object,
            *,
            assignment_name: str,
            header: str,
            clean_mode: bool,
        ) -> str:
            raise AssertionError("source comparison must not render assignments")

        def normalize_source(
            self,
            source: str,
            *,
            declaration_type: type,
            clean_mode: bool,
        ) -> str:
            assert declaration_type is int
            assert clean_mode is True
            namespace: dict[str, object] = {}
            exec(source, namespace)
            return f"value = {namespace['value']}\n"

    class DeclarationCodeDocumentDriver(MutableCodeDocumentDriver):
        def read_document(self, clean: bool = True) -> WindowCodeDocument:
            del clean
            return WindowCodeDocument(
                title="Declaration document",
                source=self.source,
                declaration_type=int,
            )

    monkeypatch.setattr(
        codegen_provider,
        "_codegen_provider",
        NormalizingCodegenProvider(),
    )
    driver = DeclarationCodeDocumentDriver("value = 1\n")

    assert driver.source_is_current("value = int(1)\n")
    assert not driver.source_is_current("value = 2\n")
    assert not driver.source_is_current("unsupported source")


def test_codegen_registration_requires_nominal_contract(monkeypatch) -> None:
    class StructuralProvider:
        def render_assignment(self, *args, **kwargs) -> str:
            return ""

        def normalize_source(self, *args, **kwargs) -> str:
            return ""

    monkeypatch.setattr(codegen_provider, "_codegen_provider", None)

    with pytest.raises(TypeError):
        CodegenProviderABC()

    with pytest.raises(TypeError, match="inherit CodegenProviderABC"):
        codegen_provider.register_codegen_provider(StructuralProvider())

    assert codegen_provider.get_codegen_provider() is None
