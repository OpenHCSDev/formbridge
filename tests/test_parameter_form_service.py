from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from enum import Enum
from typing import Annotated

import pytest

from formbridge.forms.parameter_form_service import ParameterFormService
from formbridge.forms.parameter_info_types import OptionalDataclassInfo, create_parameter_info
from formbridge.forms.parameter_type_utils import ParameterTypeUtils


class MatchSubject(Enum):
    FILE = "file"
    DIRECTORY = "directory"


class InheritableMode(Enum):
    ENABLED = "enabled"
    INHERIT = None


@dataclass(frozen=True)
class MatchClause:
    subject: MatchSubject
    value: str | None = None


@dataclass(frozen=True)
class NestedConfig:
    value: int = 1


@dataclass(frozen=True)
class NestedConfigOwner:
    primary: NestedConfig | None = None
    secondary: NestedConfig | None = None


def test_convert_value_to_type_rebuilds_optional_dataclass_tuple() -> None:
    converted = ParameterFormService().convert_value_to_type(
        [{"subject": "directory", "value": "TimePoint_1"}],
        tuple[MatchClause, ...] | None,
        "source_filters",
    )

    assert converted == (MatchClause(subject=MatchSubject.DIRECTORY, value="TimePoint_1"),)


def test_convert_value_to_type_validates_mapping_keys_and_values() -> None:
    service = ParameterFormService()

    assert service.convert_value_to_type(
        {1: "one"},
        dict[int, str],
        "labels",
    ) == {1: "one"}

    with pytest.raises(ValueError, match="expected int, got str"):
        service.convert_value_to_type(
            {"1": "one"},
            dict[int, str],
            "labels",
        )

    with pytest.raises(ValueError, match="expected str, got int"):
        service.convert_value_to_type(
            {1: 1},
            dict[int, str],
            "labels",
        )


def test_convert_value_to_type_validates_nested_list_and_tuple_items() -> None:
    service = ParameterFormService()
    annotation = dict[str, list[tuple[str, int]]]

    converted = service.convert_value_to_type(
        {"cpu": [("worker", 2)]},
        annotation,
        "routes",
    )

    assert converted == {"cpu": [("worker", 2)]}

    with pytest.raises(ValueError, match="expected int, got str"):
        service.convert_value_to_type(
            {"cpu": [("worker", "2")]},
            annotation,
            "routes",
        )


def test_convert_value_to_type_allows_int_to_float_widening() -> None:
    converted = ParameterFormService().convert_value_to_type(
        [1, 2.5],
        list[float],
        "weights",
    )

    assert converted == [1.0, 2.5]
    assert all(type(item) is float for item in converted)


def test_convert_value_to_type_rejects_bool_as_int_container_item() -> None:
    with pytest.raises(ValueError, match="expected int, got bool"):
        ParameterFormService().convert_value_to_type(
            [True],
            list[int],
            "worker_counts",
        )


def test_convert_value_to_type_resolves_annotated_union_members() -> None:
    annotation = Annotated[bool, "enabled-field"] | None

    assert (
        ParameterFormService().convert_value_to_type(
            True,
            annotation,
            "enabled",
        )
        is True
    )


def test_convert_value_to_type_accepts_enum_member_names() -> None:
    service = ParameterFormService()

    assert (
        service.convert_value_to_type("INHERIT", InheritableMode, "mode") is InheritableMode.INHERIT
    )
    assert (
        service.convert_value_to_type(
            "INHERIT",
            InheritableMode | None,
            "mode",
        )
        is InheritableMode.INHERIT
    )
    assert service.convert_value_to_type(
        ["enabled", "INHERIT"],
        list[InheritableMode],
        "modes",
    ) == [InheritableMode.ENABLED, InheritableMode.INHERIT]


def test_convert_value_to_type_preserves_callable_pattern_entries() -> None:
    def process(image):
        return image

    annotation = list[Callable | tuple[Callable, dict]] | None
    pattern = [(process, {"gain": 2})]

    converted = ParameterFormService().convert_value_to_type(
        pattern,
        annotation,
        "func",
    )

    assert converted == pattern
    assert converted[0][0] is process


def test_convert_value_to_type_rejects_noncallable_pattern_entries() -> None:
    annotation = list[Callable | tuple[Callable, dict]] | None

    with pytest.raises(
        ValueError,
        match=r"expected (?:typing\.)?Callable, got object",
    ):
        ParameterFormService().convert_value_to_type(
            [(object(), {})],
            annotation,
            "func",
        )


def test_pep604_optional_dataclass_uses_shared_optional_authority() -> None:
    annotation = NestedConfig | None

    assert ParameterTypeUtils.is_optional(annotation)
    assert ParameterTypeUtils.is_optional_dataclass(annotation)
    assert ParameterTypeUtils.get_optional_inner_type(annotation) is NestedConfig
    assert isinstance(
        create_parameter_info("config", annotation, None),
        OptionalDataclassInfo,
    )


def test_declared_nested_field_path_uses_exact_field_name() -> None:
    service = ParameterFormService()

    assert (
        service.resolve_declared_field_path(
            NestedConfigOwner,
            "primary",
            NestedConfig,
        )
        == "primary"
    )
    assert (
        service.resolve_declared_field_path(
            NestedConfigOwner,
            "secondary",
            NestedConfig,
        )
        == "secondary"
    )
    assert (
        service.resolve_declared_field_path(
            type(None),
            "function_config",
            NestedConfig,
        )
        == "function_config"
    )


def test_declared_nested_field_path_fails_on_missing_or_mismatched_owner() -> None:
    service = ParameterFormService()

    with pytest.raises(ValueError, match="no declared field 'missing'"):
        service.resolve_declared_field_path(
            NestedConfigOwner,
            "missing",
            NestedConfig,
        )

    with pytest.raises(ValueError, match="declares NestedConfig, not MatchClause"):
        service.resolve_declared_field_path(
            NestedConfigOwner,
            "primary",
            MatchClause,
        )
