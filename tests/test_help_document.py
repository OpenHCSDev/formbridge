"""Tests for the generic typed help-document model."""

import pytest
from python_introspect import DocstringInfo

from formbridge.services.help_document import (
    DEFAULT_HELP_DOCUMENT_MAX_CHARS,
    HelpDocument,
    HelpDocumentFormat,
)


@pytest.mark.parametrize(
    ("source_path", "expected"),
    [
        ("guide.md", HelpDocumentFormat.MARKDOWN),
        ("guide.MARKDOWN", HelpDocumentFormat.MARKDOWN),
        ("guide.RST", HelpDocumentFormat.RESTRUCTURED_TEXT),
        ("guide.txt", HelpDocumentFormat.PLAIN_TEXT),
        ("guide", HelpDocumentFormat.PLAIN_TEXT),
    ],
)
def test_help_document_format_is_derived_from_declared_source_suffix(
    source_path: str,
    expected: HelpDocumentFormat,
) -> None:
    assert HelpDocumentFormat.from_source_path(source_path) is expected


def test_docstring_projection_preserves_structured_sections_and_code() -> None:
    document = HelpDocument.from_docstring_info(
        DocstringInfo(
            summary="Normalize *one* stack.",
            description="Uses a [documented](https://example.com) algorithm.",
            parameters={
                "image": "Input image.",
                "tick`name": "A parameter with a delimiter in its name.",
            },
            returns="The normalized image.",
            examples='result = normalize(image)\nprint("```")',
        ),
        title="Normalize # Stack",
    )

    assert document.markup is HelpDocumentFormat.MARKDOWN
    assert document.title == "Normalize # Stack"
    assert document.content.startswith("# Normalize \\# Stack")
    assert "**Normalize \\*one\\* stack.**" in document.content
    assert "## Parameters" in document.content
    assert "### `image`" in document.content
    assert "## Returns" in document.content
    assert "## Examples" in document.content
    assert "````python" in document.content
    assert document.content.endswith("````")


def test_parameter_projection_uses_same_typed_document_model() -> None:
    document = HelpDocument.from_parameter_content(
        title="Batch size",
        summary="Images per request.",
        description="Choose a value supported by the backend.",
    )

    assert document == HelpDocument(
        content=(
            "# Batch size\n\n**Images per request.**\n\nChoose a value supported by the backend."
        ),
        markup=HelpDocumentFormat.MARKDOWN,
        title="Batch size",
    )


def test_restructured_text_rendering_preserves_hierarchy_code_and_links() -> None:
    document = HelpDocument(
        content=(
            "Guide\n"
            "=====\n\n"
            "Overview text.\n\n"
            "Section\n"
            "-------\n\n"
            "See `the reference <https://example.com/reference>`_.\n\n"
            ".. code-block:: python\n\n"
            "   result = process(image)\n"
        ),
        markup=HelpDocumentFormat.RESTRUCTURED_TEXT,
    )

    rendered = document.rendered_html()

    assert '<h1 class="title">Guide</h1>' in rendered
    assert "<h2>Section</h2>" in rendered
    assert 'href="https://example.com/reference"' in rendered
    assert "result" in rendered
    assert "<pre" in rendered


def test_restructured_text_disables_raw_html_and_file_insertion(tmp_path) -> None:
    secret = tmp_path / "secret.txt"
    secret.write_text("DO_NOT_INSERT_THIS_VALUE", encoding="utf-8")
    document = HelpDocument(
        content=(
            ".. raw:: html\n\n"
            "   <script>DO_NOT_RENDER_THIS_SCRIPT</script>\n\n"
            f".. include:: {secret}\n"
        ),
        markup=HelpDocumentFormat.RESTRUCTURED_TEXT,
    )

    rendered = document.rendered_html()

    assert "DO_NOT_RENDER_THIS_SCRIPT" not in rendered
    assert "DO_NOT_INSERT_THIS_VALUE" not in rendered
    assert "<script" not in rendered


def test_rendered_html_rejects_non_rst_documents() -> None:
    with pytest.raises(ValueError, match="only valid for reStructuredText"):
        HelpDocument("# Markdown", HelpDocumentFormat.MARKDOWN).rendered_html()


def test_bounded_uses_declaration_owned_default_and_preserves_metadata() -> None:
    document = HelpDocument(
        content="x" * (DEFAULT_HELP_DOCUMENT_MAX_CHARS + 100),
        markup=HelpDocumentFormat.MARKDOWN,
        title="Large document",
        base_url="https://example.com/docs/",
    )

    bounded = document.bounded()

    assert len(bounded.content) <= DEFAULT_HELP_DOCUMENT_MAX_CHARS
    assert bounded.content.endswith("…")
    assert bounded.markup is document.markup
    assert bounded.title == document.title
    assert bounded.base_url == document.base_url


@pytest.mark.parametrize("max_chars", [0, -1])
def test_bounded_rejects_non_positive_limits(max_chars: int) -> None:
    with pytest.raises(ValueError, match="at least 1"):
        HelpDocument("content").bounded(max_chars)


def test_bounded_returns_same_immutable_document_when_already_within_limit() -> None:
    document = HelpDocument("short")

    assert document.bounded(5) is document


def test_bounded_respects_very_small_limits() -> None:
    assert HelpDocument("content").bounded(1).content == "…"
    assert HelpDocument("content").bounded(2).content == "c…"
    assert HelpDocument("content").bounded(4).content == "c\n\n…"


@pytest.mark.parametrize(
    ("document", "title", "expected"),
    [
        (
            HelpDocument(
                "\n# Processing Guide #\n\nFirst section.",
                HelpDocumentFormat.MARKDOWN,
            ),
            "processing guide",
            "First section.",
        ),
        (
            HelpDocument(
                "\nProcessing Guide\n================\n\nFirst section.",
                HelpDocumentFormat.RESTRUCTURED_TEXT,
            ),
            "processing guide",
            "First section.",
        ),
    ],
)
def test_matching_leading_heading_is_removed(
    document: HelpDocument,
    title: str,
    expected: str,
) -> None:
    assert document.without_leading_heading(title).content == expected


@pytest.mark.parametrize(
    "document",
    [
        HelpDocument("# Different Guide\n\nContent", HelpDocumentFormat.MARKDOWN),
        HelpDocument(
            "Different Guide\n===============\n\nContent",
            HelpDocumentFormat.RESTRUCTURED_TEXT,
        ),
        HelpDocument("Processing Guide\nContent", HelpDocumentFormat.PLAIN_TEXT),
    ],
)
def test_nonmatching_or_plain_heading_is_unchanged(document: HelpDocument) -> None:
    assert document.without_leading_heading("Processing Guide") is document
