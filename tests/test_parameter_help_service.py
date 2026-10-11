"""Tests for shared parameter help introspection."""

from dataclasses import dataclass, fields
from typing import Annotated

from formbridge.services.parameter_help_service import (
    dataclass_parameter_descriptions,
    parameter_help_content,
)
from formbridge.strategies.preview_formatting import FormattingConfig


def test_preview_policy_fields_include_authored_help_for_hidden_controls() -> None:
    descriptions = dataclass_parameter_descriptions(FormattingConfig)
    assert set(descriptions) == {field.name for field in fields(FormattingConfig)}
    assert {
        name for name, description in descriptions.items() if not (description or "").strip()
    } == set()


def test_dataclass_docstring_help_falls_back_when_source_is_unavailable(monkeypatch):
    from formbridge.services import parameter_help_service
    from formbridge.services.parameter_help_service import docstring_info_for_target

    @dataclass
    class GeneratedLikeConfig:
        """Generated-like config summary."""

        value: int = 1

    def raise_source_unavailable(_target):
        raise OSError("could not find class definition")

    monkeypatch.setattr(
        parameter_help_service.inspect,
        "getsource",
        raise_source_unavailable,
    )

    docstring_info = docstring_info_for_target(GeneratedLikeConfig)

    assert docstring_info.summary == "Generated-like config summary."
    assert docstring_info.description is None


def test_parameter_help_projects_annotated_owner_type_without_metadata_repr() -> None:
    content = parameter_help_content(
        param_name="colormap",
        param_type=Annotated[str, "non-empty"],
        description="Napari colormap name.",
    )

    assert content.summary == "• colormap (str)"
    assert content.description == "Napari colormap name."
