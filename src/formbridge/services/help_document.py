"""Generic rich help-document content shared by help surfaces."""

from __future__ import annotations

import re
from dataclasses import dataclass, replace
from enum import StrEnum
from pathlib import PurePath

from docutils.core import publish_parts
from python_introspect import DocstringInfo

DEFAULT_HELP_DOCUMENT_MAX_CHARS = 50_000


class HelpDocumentFormat(StrEnum):
    """Markup format owned by one help document."""

    PLAIN_TEXT = "plain_text"
    MARKDOWN = "markdown"
    RESTRUCTURED_TEXT = "restructured_text"

    @classmethod
    def from_source_path(cls, source_path: str) -> HelpDocumentFormat:
        """Resolve markup from a source document's declared filename."""
        suffix = PurePath(source_path).suffix.casefold()
        if suffix in {".md", ".markdown"}:
            return cls.MARKDOWN
        if suffix == ".rst":
            return cls.RESTRUCTURED_TEXT
        return cls.PLAIN_TEXT


@dataclass(frozen=True, slots=True)
class HelpDocument:
    """One renderer-ready help document with explicit markup provenance."""

    content: str
    markup: HelpDocumentFormat = HelpDocumentFormat.PLAIN_TEXT
    title: str | None = None
    base_url: str | None = None

    @classmethod
    def from_docstring_info(
        cls,
        docstring_info: DocstringInfo,
        *,
        title: str | None = None,
    ) -> HelpDocument:
        """Project structured introspection into one Markdown document."""
        sections: list[str] = []
        if title:
            sections.append(f"# {_markdown_heading(title)}")
        if docstring_info.summary:
            sections.append(f"**{_markdown_inline(docstring_info.summary)}**")
        if docstring_info.description:
            sections.append(docstring_info.description.strip())
        if docstring_info.parameters:
            parameter_sections = ["## Parameters"]
            for name, description in docstring_info.parameters.items():
                parameter_sections.append(f"### {_markdown_code_span(name)}")
                if description:
                    parameter_sections.append(description.strip())
            sections.append("\n\n".join(parameter_sections))
        if docstring_info.returns:
            sections.append(f"## Returns\n\n{docstring_info.returns.strip()}")
        if docstring_info.examples:
            fence = _code_fence(docstring_info.examples)
            sections.append(
                f"## Examples\n\n{fence}python\n" f"{docstring_info.examples.rstrip()}\n{fence}"
            )
        return cls(
            content="\n\n".join(section for section in sections if section),
            markup=HelpDocumentFormat.MARKDOWN,
            title=title,
        )

    @classmethod
    def from_parameter_content(
        cls,
        *,
        summary: str,
        description: str,
        title: str | None = None,
    ) -> HelpDocument:
        """Project one parameter-help response into the shared document model."""
        sections = []
        if title:
            sections.append(f"# {_markdown_heading(title)}")
        if summary:
            sections.append(f"**{_markdown_inline(summary)}**")
        if description:
            sections.append(description.strip())
        return cls(
            content="\n\n".join(sections),
            markup=HelpDocumentFormat.MARKDOWN,
            title=title,
        )

    def rendered_html(self) -> str:
        """Render reStructuredText safely for Qt's rich-text engine."""
        if self.markup is not HelpDocumentFormat.RESTRUCTURED_TEXT:
            raise ValueError("rendered_html() is only valid for reStructuredText documents")
        parts = publish_parts(
            self.content,
            writer_name="html5",
            settings_overrides={
                "raw_enabled": False,
                "file_insertion_enabled": False,
                "report_level": 5,
                "halt_level": 6,
                "output_encoding": "unicode",
                "embed_stylesheet": False,
            },
        )
        return str(parts["html_body"])

    def bounded(
        self,
        max_chars: int = DEFAULT_HELP_DOCUMENT_MAX_CHARS,
    ) -> HelpDocument:
        """Return this document with a renderer-safe content bound."""
        if max_chars < 1:
            raise ValueError("max_chars must be at least 1")
        if len(self.content) <= max_chars:
            return self
        if max_chars < 4:
            content = f"{self.content[: max_chars - 1]}…"
        else:
            content = f"{self.content[: max_chars - 3].rstrip()}\n\n…"
        return replace(self, content=content)

    def without_leading_heading(self, expected_title: str) -> HelpDocument:
        """Remove a matching source heading when chrome already displays it."""
        lines = self.content.splitlines()
        first_content_index = next(
            (index for index, line in enumerate(lines) if line.strip()),
            None,
        )
        if first_content_index is None:
            return self
        normalized_expected = _normalized_heading(expected_title)

        if self.markup is HelpDocumentFormat.MARKDOWN:
            match = re.match(r"^\s{0,3}#{1,6}\s+(.+?)\s*#*\s*$", lines[first_content_index])
            if match is None or _normalized_heading(match.group(1)) != normalized_expected:
                return self
            del lines[first_content_index]
        elif self.markup is HelpDocumentFormat.RESTRUCTURED_TEXT:
            underline_index = first_content_index + 1
            if underline_index >= len(lines):
                return self
            title = lines[first_content_index].strip()
            underline = lines[underline_index].strip()
            if (
                _normalized_heading(title) != normalized_expected
                or len(set(underline)) != 1
                or next(iter(set(underline)), "") not in "=-~^\"'`:+*#<>_"
                or len(underline) < len(title)
            ):
                return self
            del lines[first_content_index : underline_index + 1]
        else:
            return self

        while lines and not lines[0].strip():
            del lines[0]
        return replace(self, content="\n".join(lines))


def _markdown_heading(value: str) -> str:
    return " ".join(value.split()).replace("#", r"\#")


def _markdown_inline(value: str) -> str:
    normalized = " ".join(value.split())
    return re.sub(r"([\\`*_[\]<>])", r"\\\1", normalized)


def _markdown_code_span(value: str) -> str:
    delimiter = "`" * max(1, _longest_character_run(value, "`") + 1)
    padding = " " if value.startswith(("`", " ")) or value.endswith(("`", " ")) else ""
    return f"{delimiter}{padding}{value}{padding}{delimiter}"


def _code_fence(value: str) -> str:
    return "`" * max(3, _longest_character_run(value, "`") + 1)


def _longest_character_run(value: str, target: str) -> int:
    longest_run = 0
    current_run = 0
    for character in value:
        if character == target:
            current_run += 1
            longest_run = max(longest_run, current_run)
        else:
            current_run = 0
    return longest_run


def _normalized_heading(value: str) -> str:
    return " ".join(value.split()).casefold()
