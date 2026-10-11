"""Qt-free parameter help introspection shared by forms, help windows, and agents."""

from __future__ import annotations

import ast
import inspect
import logging
import re
from dataclasses import dataclass, fields, is_dataclass
from enum import Enum
from types import UnionType
from typing import Annotated, Callable, Optional, Union, get_args, get_origin

from objectstate.lazy_factory import get_base_type_for_lazy, is_lazy_dataclass
from python_introspect import (
    DocstringExtractor,
    DocstringInfo,
    UnifiedParameterAnalyzer,
    resolve_annotated,
)

logger = logging.getLogger(__name__)

NO_PARAMETER_DESCRIPTION = "No description available"


@dataclass(frozen=True, slots=True)
class ParameterHelpContent:
    """Display-ready content for one parameter help popup."""

    summary: str
    description: str


@dataclass(frozen=True, slots=True)
class ParsedParameterDescription:
    """Structured projection of the generated parameter documentation prefix."""

    type_name: str | None
    default_value: str | None
    description: str


@dataclass(frozen=True, slots=True)
class ParameterDescriptionBody:
    """Formatted body fields for one parsed parameter description."""

    setting_name: str | None
    description: str


class DataclassDocstringResolutionKind(Enum):
    """Provenance for source-authored dataclass docstring resolution."""

    FOUND = "found"
    CLASS_NOT_FOUND = "class_not_found"
    DOCSTRING_MISSING = "docstring_missing"


@dataclass(frozen=True, slots=True)
class DataclassDocstringResolution:
    """Result of resolving a source-authored dataclass docstring."""

    kind: DataclassDocstringResolutionKind
    docstring: str | None


@dataclass(frozen=True, slots=True)
class ParameterDescriptionFormatter:
    """Display formatter for compact parameter help prose."""

    def strip_rst_directives(self, text: str) -> str:
        """Remove inline RST directives that are not useful in a compact popup."""
        text = re.sub(r"\s*\.\. image:: \{[^}]+\}", "", text)
        text = re.sub(r"\s*\.\. _\w+:\s+\S+", "", text)
        return text.strip()

    def format_inline_list_markers(self, text: str) -> str:
        """Give flattened CellProfiler list markers paragraph breaks."""
        text = re.sub(r"\s+-\s+(\{[^}]+\}:)", r"\n\n- \1", text)
        text = re.sub(r"\s+References\s+-\s+", "\n\nReferences\n\n- ", text)
        text = text.replace(" NOTE ", "\n\nNOTE ")
        return text.strip()

    def format_body(self, text: str) -> str:
        """Return display-ready body prose for parameter help."""
        return self.format_inline_list_markers(self.strip_rst_directives(text))

PARAMETER_DESCRIPTION_FORMATTER = ParameterDescriptionFormatter()


def dataclass_type_for_target(target: Union[Callable, type, None]) -> type | None:
    """Return the dataclass type represented by a help target."""
    if target is None:
        return None
    if inspect.isclass(target) and is_dataclass(target):
        return target
    target_type = type(target)
    if is_dataclass(target_type):
        return target_type
    return None


def source_dataclass_type(dataclass_type: type) -> type:
    """Return the source-authored dataclass for generated lazy dataclass types."""
    if is_lazy_dataclass(dataclass_type):
        base_type = get_base_type_for_lazy(dataclass_type)
        if base_type is None:
            raise RuntimeError(
                f"Lazy dataclass {dataclass_type.__qualname__} is missing its "
                "registered source dataclass type."
            )
        if not is_dataclass(base_type):
            raise RuntimeError(
                f"Lazy dataclass {dataclass_type.__qualname__} resolves to "
                f"non-dataclass source type {base_type!r}."
            )
        return base_type

    return dataclass_type


def source_class_docstring_resolution(dataclass_type: type) -> DataclassDocstringResolution:
    """Extract the authored class docstring instead of dataclass' rendered signature."""
    source_type = source_dataclass_type(dataclass_type)
    try:
        source = inspect.getsource(source_type)
    except (OSError, TypeError):
        return DataclassDocstringResolution(
            kind=DataclassDocstringResolutionKind.CLASS_NOT_FOUND,
            docstring=None,
        )
    tree = ast.parse(source)

    for node in ast.walk(tree):
        if isinstance(node, ast.ClassDef) and node.name == source_type.__name__:
            docstring = ast.get_docstring(node)
            if docstring is None:
                return DataclassDocstringResolution(
                    kind=DataclassDocstringResolutionKind.DOCSTRING_MISSING,
                    docstring=None,
                )
            return DataclassDocstringResolution(
                kind=DataclassDocstringResolutionKind.FOUND,
                docstring=docstring,
            )
    return DataclassDocstringResolution(
        kind=DataclassDocstringResolutionKind.CLASS_NOT_FOUND,
        docstring=None,
    )


def is_signature_docstring(text: str | None, type_name: str) -> bool:
    """Return whether a dataclass docstring is just the generated constructor signature."""
    if text is None:
        return False
    return text.lstrip().startswith(f"{type_name}(")


def class_docstring_text(dataclass_type: type) -> str | None:
    """Return a human-authored dataclass docstring when one is available."""
    source_type = source_dataclass_type(dataclass_type)
    source_docstring = source_class_docstring_resolution(source_type)
    if source_docstring.kind is DataclassDocstringResolutionKind.FOUND:
        return source_docstring.docstring
    logger.debug(
        "Dataclass source docstring resolution for %s ended with %s.",
        source_type.__qualname__,
        source_docstring.kind.value,
    )

    inspected_docstring = inspect.getdoc(source_type)
    if is_signature_docstring(inspected_docstring, source_type.__name__):
        return None
    return inspected_docstring


def split_docstring_summary(docstring: str | None, fallback: str) -> tuple[str, str | None]:
    """Split a docstring into summary and optional remaining description."""
    if not docstring:
        return fallback, None
    lines = docstring.strip().splitlines()
    if not lines:
        summary = fallback
    else:
        summary = lines[0].strip()
    description = "\n".join(line.rstrip() for line in lines[1:]).strip()
    if description == "":
        return summary, None
    return summary, description


def dataclass_type_from_annotation(annotation) -> type | None:
    """Return a dataclass type represented by a field annotation."""
    if inspect.isclass(annotation) and is_dataclass(annotation):
        return annotation

    origin = get_origin(annotation)
    if origin is Annotated:
        annotated_args = get_args(annotation)
        if not annotated_args:
            return None
        return dataclass_type_from_annotation(annotated_args[0])

    if origin in (Union, UnionType):
        dataclass_args = tuple(
            arg for arg in get_args(annotation)
            if inspect.isclass(arg) and is_dataclass(arg)
        )
        if len(dataclass_args) == 1:
            return dataclass_args[0]
    return None


def dataclass_field_description(description: str | None, annotation) -> str | None:
    """Return displayable docs for one dataclass field."""
    field_type = dataclass_type_from_annotation(annotation)
    signature_type_names: tuple[str, ...] = ()
    if field_type is not None:
        source_type = source_dataclass_type(field_type)
        signature_type_names = tuple(
            dict.fromkeys((field_type.__name__, source_type.__name__))
        )
    if description and (
        field_type is None
        or not any(
            is_signature_docstring(description, type_name)
            for type_name in signature_type_names
        )
    ):
        return description

    if field_type is None:
        return description

    class_docstring = class_docstring_text(field_type)
    summary, description_body = split_docstring_summary(
        class_docstring,
        f"{source_dataclass_type(field_type).__name__} configuration fields.",
    )
    if description_body:
        return f"{summary}\n\n{description_body}"
    return summary


def dataclass_parameter_descriptions(dataclass_type: type) -> dict[str, str]:
    """Return field descriptions for a dataclass using the shared introspection path."""
    analyzed = UnifiedParameterAnalyzer.analyze(dataclass_type)
    dataclass_fields = {field.name: field for field in fields(dataclass_type)}
    descriptions: dict[str, str] = {}
    for name, info in analyzed.items():
        if name in dataclass_fields:
            annotation = dataclass_fields[name].type
        else:
            annotation = None
        description = dataclass_field_description(info.description, annotation)
        if description:
            descriptions[name] = description
    return descriptions


def docstring_info_for_target(target: Union[Callable, type]) -> DocstringInfo:
    """Return help-window documentation, using field docs for dataclass targets."""
    dataclass_type = dataclass_type_for_target(target)
    if dataclass_type is None:
        docstring_info = DocstringExtractor.extract(target)
        parameters = dict(docstring_info.parameters or {})
        for name, parameter_info in UnifiedParameterAnalyzer.analyze(target).items():
            if name not in parameters and parameter_info.description:
                parameters[name] = parameter_info.description
        return docstring_info._replace(parameters=parameters)

    source_type = source_dataclass_type(dataclass_type)
    summary, description = split_docstring_summary(
        class_docstring_text(dataclass_type),
        source_type.__name__,
    )
    return DocstringInfo(
        summary=summary,
        description=description,
        parameters=dataclass_parameter_descriptions(source_type),
        returns="",
        examples="",
    )


def parameter_description_from_target(
    help_target: Union[Callable, type, None],
    param_name: str,
) -> Optional[str]:
    """Return parsed documentation for one parameter from a callable/class target."""
    if help_target is None:
        return None

    parameters = docstring_info_for_target(help_target).parameters or {}
    return parameters.get(param_name)


def resolved_parameter_description(
    *,
    help_target: Union[Callable, type, None],
    param_name: str,
    widget_description: str,
) -> str:
    """Resolve parameter help text from target docs, then explicit widget metadata."""
    target_description = parameter_description_from_target(help_target, param_name)
    if target_description:
        return target_description
    if widget_description:
        return widget_description
    return NO_PARAMETER_DESCRIPTION


def parameter_type_display(param_type: type | None) -> str:
    """Return the compact type label used by parameter help."""
    if param_type is None:
        return ""
    display_type = resolve_annotated(param_type)
    if isinstance(display_type, type):
        return f" ({display_type.__name__})"
    return f" ({display_type})"


def split_default_prefix(text: str) -> tuple[str, str]:
    """Split a rendered default literal from the following sentence body."""
    sentence_separator = ". "
    separator_index = text.find(sentence_separator)
    if separator_index >= 0:
        return (
            text[:separator_index],
            text[separator_index + len(sentence_separator) :],
        )
    return text.rstrip("."), ""


def parse_parameter_description(description: str) -> ParsedParameterDescription:
    """Parse the type/default prefix emitted by DocstringExtractor parameter docs."""
    if not description.startswith("'"):
        unquoted_match = re.match(
            r"^(?P<type>[^.;]+);\s+default\s+(?P<default_and_body>.*)$",
            description,
        )
        if unquoted_match is not None:
            default_value, body = split_default_prefix(
                unquoted_match.group("default_and_body"),
            )
            return ParsedParameterDescription(
                type_name=unquoted_match.group("type").strip(),
                default_value=default_value.strip(),
                description=body.strip(),
            )
        return ParsedParameterDescription(
            type_name=None,
            default_value=None,
            description=description,
        )

    closing_quote_index = description.find("'", 1)
    if closing_quote_index < 0:
        return ParsedParameterDescription(
            type_name=None,
            default_value=None,
            description=description,
        )

    type_name = description[1:closing_quote_index]
    remainder = description[closing_quote_index + 1 :].lstrip()
    if remainder.startswith("."):
        remainder = remainder[1:].lstrip()

    default_value = None
    default_prefix = "; default "
    if remainder.startswith(default_prefix):
        default_value, remainder = split_default_prefix(remainder[len(default_prefix) :])

    return ParsedParameterDescription(
        type_name=type_name,
        default_value=default_value,
        description=remainder,
    )


def parameter_description_body(description: str) -> ParameterDescriptionBody:
    """Split CellProfiler setting metadata from the prose body."""
    setting_prefix = "CellProfiler setting '"
    if not description.startswith(setting_prefix):
        return ParameterDescriptionBody(
            setting_name=None,
            description=PARAMETER_DESCRIPTION_FORMATTER.format_body(description),
        )

    setting_start = len(setting_prefix)
    setting_end = description.find("'", setting_start)
    if setting_end < 0:
        return ParameterDescriptionBody(
            setting_name=None,
            description=PARAMETER_DESCRIPTION_FORMATTER.format_body(description),
        )

    setting_name = description[setting_start:setting_end]
    remainder = description[setting_end + 1 :].lstrip()
    if remainder.startswith("."):
        remainder = remainder[1:].lstrip()
    return ParameterDescriptionBody(
        setting_name=setting_name,
        description=PARAMETER_DESCRIPTION_FORMATTER.format_body(remainder),
    )


def _default_values_match(left: str, right: str) -> bool:
    """Return whether two rendered default literals describe the same value."""
    if left == right:
        return True
    numeric_pattern = r"[-+]?\d+(?:\.\d+)?"
    if re.fullmatch(numeric_pattern, left) and re.fullmatch(numeric_pattern, right):
        return float(left) == float(right)
    return False


def remove_duplicate_default_sentence(description: str, default_value: str | None) -> str:
    """Remove body-level default sentence already shown in the default section."""
    if default_value is None:
        return description

    def replacement(match: re.Match[str]) -> str:
        rendered_default = match.group("value").strip()
        if _default_values_match(default_value, rendered_default):
            return ""
        return match.group(0)

    return re.sub(
        r"(?:\s+|^)Default is (?P<value>[-+]?\d+(?:\.\d+)?|[^.]+)\.",
        replacement,
        description,
    ).strip()


def parameter_help_content(
    *,
    param_name: str,
    param_type: type | None,
    description: str,
) -> ParameterHelpContent:
    """Build compact popup content without leaking raw Python annotations."""
    parsed = parse_parameter_description(description)
    type_str = f" ({parsed.type_name})" if parsed.type_name else parameter_type_display(param_type)
    body = parameter_description_body(parsed.description)
    lines: list[str] = []
    if parsed.default_value:
        lines.append(f"Default: {parsed.default_value}")
    if body.setting_name:
        lines.append(f"CellProfiler setting: {body.setting_name}")
    body_description = remove_duplicate_default_sentence(
        body.description,
        parsed.default_value,
    )
    if body_description:
        lines.append(body_description)
    return ParameterHelpContent(
        summary=f"• {param_name}{type_str}",
        description="\n\n".join(lines) if lines else NO_PARAMETER_DESCRIPTION,
    )
