"""A declared field reads its bounds, search text and page from the dataclass declaration."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Annotated

import pytest
from annotated_types import Ge, Interval, Le
from objectstate import ObjectState, set_base_config_type
from python_introspect import FieldLabel

from formbridge.forms.declared_fields import FieldPath, FormPage, form_pages
from formbridge.forms.parameter_form_service import ParameterFormService

LOOK = FormPage("Look")
WORK = FormPage("Work")


@dataclass(frozen=True)
class Inner:
    rows: Annotated[int, FieldLabel("Rows shown"), Ge(1), Le(10)] = 2
    ratio: Annotated[float, Interval(gt=0)] = 1.0
    name: str = "plain"


@dataclass(frozen=True)
class Paged:
    look: Annotated[Inner, FieldLabel("Appearance"), LOOK] = field(default_factory=Inner)
    work: Annotated[Inner, WORK] = field(default_factory=Inner)
    more: Annotated[Inner, LOOK] = field(default_factory=Inner)


@dataclass(frozen=True)
class HalfPaged:
    look: Annotated[Inner, LOOK] = field(default_factory=Inner)
    loose: Inner = field(default_factory=Inner)


def state_of(value: object) -> ObjectState:
    set_base_config_type(type(value))
    return ObjectState(value)


def shown(state: ObjectState):
    return [path for path, _ in ParameterFormService().parameters_for_state(state, "")]


def test_bounds_merge_every_declared_bound():
    state = state_of(Paged())
    rows = FieldPath(Paged).look.rows.bind(state)
    assert (rows.interval.ge, rows.interval.le) == (1, 10)
    assert rows.bounds_text == ">= 1, <= 10"
    assert FieldPath(Paged).look.ratio.bind(state).bounds_text == "> 0"
    assert FieldPath(Paged).look.name.bind(state).bounds_text == ""


def test_search_text_holds_every_enclosing_label():
    state = state_of(Paged())
    assert FieldPath(Paged).look.rows.bind(state).search_text == "appearance rows shown"


def test_pages_follow_the_fields_that_name_them_in_declaration_order():
    state = state_of(Paged())
    pages = form_pages(state, shown(state))
    assert list(pages) == [LOOK, WORK]
    assert [path.value for path in pages[LOOK]] == ["look", "more"]


def test_a_paged_form_refuses_a_top_level_field_without_a_page():
    state = state_of(HalfPaged())
    with pytest.raises(TypeError, match="loose"):
        form_pages(state, shown(state))
