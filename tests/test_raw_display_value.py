"""The edited/shown value pair keeps each field's supplier recoverable."""

from __future__ import annotations

from dataclasses import dataclass

import pytest

from formbridge.forms.raw_display_value import RawDisplayValue


@dataclass(frozen=True)
class Settings:
    names: tuple[str, ...] | None = None
    limit: int | None = 3


@dataclass(frozen=True)
class Narrow(Settings):
    pass


@dataclass(frozen=True)
class Other:
    names: tuple[str, ...] | None = None


def test_shown_as_edited_has_no_inherited_fields() -> None:
    value = RawDisplayValue.shown_as_edited(Settings, Settings(names=("a",)))

    assert value.display is value.raw
    assert not value.shows_inherited("names")
    assert value.declared_type is Settings


def test_inherited_field_is_distinguished_from_a_declared_one() -> None:
    value = RawDisplayValue(Settings, Settings(names=None), Settings(names=("a",)))
    declared = RawDisplayValue.shown_as_edited(Settings, Settings(names=("a",)))

    assert value.display_field("names") == declared.display_field("names")
    assert value.shows_inherited("names")
    assert not declared.shows_inherited("names")


def test_replacing_changes_raw_and_display_together() -> None:
    value = RawDisplayValue(Settings, Settings(names=None), Settings(names=("a",)))

    edited = value.replacing(names=("b",))

    assert edited.raw == Settings(names=("b",))
    assert edited.display == Settings(names=("b",))
    assert not edited.shows_inherited("names")


def test_differently_shown_fields_names_only_changed_fields() -> None:
    before = RawDisplayValue.shown_as_edited(Settings, Settings(names=("a",), limit=1))
    after = before.displaying(Settings(names=("a",), limit=2))

    assert before.differently_shown_fields(after, ("names", "limit")) == ("limit",)
    assert before.differently_shown_fields(after, ("names",)) == ()


def test_field_default_comes_from_the_dataclass() -> None:
    value = RawDisplayValue.shown_as_edited(Settings, Settings(limit=9))

    assert value.field_default("limit") == 3


def test_foreign_types_are_rejected() -> None:
    with pytest.raises(TypeError, match="Expected Settings, got Other"):
        RawDisplayValue.shown_as_edited(Settings, Other())
    with pytest.raises(TypeError, match="Displayed value must be Narrow"):
        RawDisplayValue(Settings, Narrow(), Settings())
