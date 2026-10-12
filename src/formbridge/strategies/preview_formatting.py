"""Declaration-driven formatting for manager list-item previews."""

from __future__ import annotations

from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, TypeAlias

from objectstate import DottedFieldPath, ParameterOwner
from objectstate.lazy_factory import get_group_abbreviation

from formbridge.utils.preview_formatters import (
    PreviewFieldFormatRequest,
    PreviewValueDetail,
    format_preview_value,
)

if TYPE_CHECKING:
    from objectstate import ObjectState

PreviewSegment: TypeAlias = tuple[str, str | None, str | None]
PreviewValueFormatter: TypeAlias = Callable[[PreviewFieldFormatRequest], str | None]
ItemValueFormatter: TypeAlias = Callable[[object], str | None]


@dataclass(frozen=True, slots=True)
class FormattingConfig:
    """List-preview presentation derived from declared fields and ObjectState.

    These rules affect only displayed text. Full values, editing, field-level
    provenance and saved configuration remain unchanged.
    """

    wrap_lines: bool = False
    """Wrap complete list items to panel width and grow rows; disable for horizontal scrolling."""

    show_detail_line: bool = True
    """Show the declared detail line, such as a plate's full input path."""

    show_active_configs: bool = True
    """Include enabled configurations and their declaration-owned always-viewable fields."""

    show_modified_fields: bool = True
    """Add fields differing from their signature defaults to the declared preview fields."""

    show_group_labels: bool = True
    """Show configuration group headings using each owner's declared abbreviation."""

    collection_detail: PreviewValueDetail = PreviewValueDetail.COMPACT
    """Summarize collections by count or expand contents; enum sequences keep readable names."""

    max_value_length: int = 96
    """Maximum characters per value, with an ellipsis for longer values; zero shows all text."""

    group_separator: str = field(default=" | ", metadata={"ui_hidden": True})
    """Text before each labelled configuration group after the first group."""

    field_separator: str = field(default=", ", metadata={"ui_hidden": True})
    """Text between successive field values within one configuration group."""

    closing_brace_separator: str = field(default="", metadata={"ui_hidden": True})
    """Text before the closing brace of each labelled configuration group."""

    container_abbr_func: Callable[[type], str] = field(
        default=get_group_abbreviation, metadata={"ui_hidden": True}
    )
    """Function mapping a configuration declaration type to its preview heading.

    The default resolves the registered abbreviation through the declaration's
    method resolution order, or uses its class name before the first underscore.
    """

    def __post_init__(self) -> None:
        if self.max_value_length < 0:
            raise ValueError("max_value_length must be non-negative")

    def format_value(self, value: object) -> str | None:
        text = format_preview_value(value, self.collection_detail)
        if text is not None and self.max_value_length and len(text) > self.max_value_length:
            return text[: self.max_value_length - 1] + "…"
        return text


@dataclass(frozen=True, slots=True)
class _PreviewField:
    """One rendered field in a preview group."""

    field_path: str
    label: str


@dataclass(slots=True)
class _PreviewGroup:
    """Fields sharing one authoritative ObjectState container path."""

    container_path: DottedFieldPath
    owner: ParameterOwner
    fields: list[_PreviewField] = field(default_factory=list)

    def add(self, field_path: str, label: str) -> None:
        """Append one field to this render-cycle projection."""
        self.fields.append(_PreviewField(field_path=field_path, label=label))

    def heading(self, config: FormattingConfig) -> tuple[str, str | None]:
        """Derive the heading from the ObjectState container path and owner."""
        if not self.container_path.parts:
            return "root", None
        if not isinstance(self.owner, type):
            raise TypeError(
                f"Preview container {self.container_path.value!r} requires a type declaration"
            )
        return (
            config.container_abbr_func(self.owner),
            self.container_path.value,
        )


class _PreviewSegmentBuilder:
    """Group formatted fields without copying their declaration metadata."""

    def __init__(self, formatting_config: FormattingConfig) -> None:
        self.config = formatting_config
        self._groups: dict[DottedFieldPath, _PreviewGroup] = {}

    def add_field(
        self,
        field_path: str,
        label: str,
        container_path: DottedFieldPath,
        container_owner: ParameterOwner,
    ) -> None:
        """Add a formatted field to its declaration-owned presentation group."""
        group = self._groups.get(container_path)
        if group is None:
            group = _PreviewGroup(
                container_path=container_path,
                owner=container_owner,
            )
            self._groups[container_path] = group
        elif group.owner is not container_owner:
            raise TypeError(
                f"Preview container {container_path.value!r} has inconsistent declarations"
            )
        group.add(field_path, label)

    def build(self) -> list[PreviewSegment]:
        """Render groups in the order their first field was added."""
        segments: list[PreviewSegment] = []
        for index, group in enumerate(self._groups.values()):
            segments.extend(self._render_group(group, is_first_group=index == 0))
        return segments

    def _render_group(
        self,
        group: _PreviewGroup,
        *,
        is_first_group: bool,
    ) -> list[PreviewSegment]:
        segments: list[PreviewSegment] = []
        if self.config.show_group_labels:
            abbreviation, abbreviation_path = group.heading(self.config)
            if is_first_group:
                group_separator = ""
            else:
                group_separator = self.config.group_separator
            segments.extend(
                (
                    (abbreviation, abbreviation_path, group_separator),
                    ("{", None, ""),
                )
            )

        for index, preview_field in enumerate(group.fields):
            if index == 0:
                if self.config.show_group_labels:
                    separator = ""
                else:
                    separator = None
            else:
                separator = self.config.field_separator
            segments.append((preview_field.label, preview_field.field_path, separator))

        if self.config.show_group_labels:
            segments.append(("}", None, self.config.closing_brace_separator))
        return segments


class ObjectStatePreviewFormattingService:
    """Format resolved ObjectState values using their recorded declarations."""

    def __init__(self, config: FormattingConfig) -> None:
        self.config = config

    def collect_and_render(
        self,
        state: ObjectState | None,
        field_paths: Sequence[str],
        formatters: Mapping[str, ItemValueFormatter],
        field_value_formatter: PreviewValueFormatter,
    ) -> list[PreviewSegment]:
        """Collect declared fields and return their rendered segments."""
        if state is None:
            return []

        builder = _PreviewSegmentBuilder(self.config)
        for field_path in field_paths:
            value = state.get_resolved_value(field_path)
            if value is None:
                continue

            field_owner = self._field_owner_for_path(state, field_path)
            formatter = formatters.get(field_path)
            if formatter is None:
                label = field_value_formatter(
                    PreviewFieldFormatRequest(
                        field_path=field_path,
                        value=value,
                        field_owner=field_owner,
                        value_formatter=self.config.format_value,
                    )
                )
            else:
                label = formatter(value)
            if not label:
                continue

            container_path = self._container_path(field_path)
            builder.add_field(
                field_path,
                label,
                container_path,
                self._field_owner_for_path(state, container_path.value),
            )
        return builder.build()

    @staticmethod
    def _field_owner_for_path(
        state: ObjectState,
        field_path: str,
    ) -> ParameterOwner:
        declaration = state.type_for_path(field_path)
        if not isinstance(declaration, type) and not callable(declaration):
            raise TypeError(
                f"Preview field {field_path!r} requires a nominal type or callable declaration"
            )
        return declaration

    @staticmethod
    def _container_path(field_path: str) -> DottedFieldPath:
        if "." not in field_path:
            return DottedFieldPath("")
        return DottedFieldPath(field_path.rsplit(".", 1)[0])
