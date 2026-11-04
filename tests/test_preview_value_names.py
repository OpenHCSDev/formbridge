"""Class-valued choices have readable captions without changing their identity."""

from abc import ABCMeta
from dataclasses import dataclass

import pytest
from objectstate.lazy_factory import LazyDataclassFactory

from formbridge.forms.ui_utils import FieldDisplayText
from formbridge.managers.preview_formatting import ManagerPreviewFieldFormatter
from formbridge.utils.preview_formatters import PreviewFieldFormatRequest, format_preview_value


@pytest.mark.parametrize(
    ("name", "expected"),
    [
        ("read_previous_step", "Read Previous Step"),
        ("ReadPreviousStep", "Read Previous Step"),
        ("SourceVoxelSpacing", "Source Voxel Spacing"),
        ("HTTPServer", "HTTP Server"),
        ("Channel", "Channel"),
    ],
)
def test_display_text_owns_parameter_and_class_name_spacing(name: str, expected: str) -> None:
    text = FieldDisplayText.from_field_name(name)
    assert text.display_name == expected
    assert text.field_label == f"{expected}:"
    assert text.checkbox_label == f"Enable {expected}"
    assert text.group_title == expected


@pytest.mark.parametrize("metaclass", [type, ABCMeta])
def test_class_valued_choice_uses_shared_preview_formatter(metaclass: type) -> None:
    choice = metaclass("ReadPreviousStep", (), {"name": "previous"})
    assert format_preview_value(choice) == "Read Previous Step"
    request = PreviewFieldFormatRequest("processing.input_source", choice, object)
    assert ManagerPreviewFieldFormatter().format_field(request) == "input_source:Read Previous Step"
    assert request.value is choice
    assert choice.name == "previous"


def test_lazy_class_caption_uses_the_original_declaration() -> None:
    @dataclass
    class SourceVoxelSpacing:
        value: int = 1

    lazy = LazyDataclassFactory.make_lazy_simple(SourceVoxelSpacing, "LazyCaptionSpacing")
    assert format_preview_value(lazy) == "Source Voxel Spacing"


def test_callable_preview_keeps_function_name() -> None:
    def read_previous_step() -> None:
        pass

    assert format_preview_value(read_previous_step) == "read_previous_step"
