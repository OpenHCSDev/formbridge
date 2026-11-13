"""A view family is the inheritance tree below it; each class declares what it shows."""

from typing import Annotated

import pytest

from formbridge.forms.declared_fields import DeclaredMetadata, DeclaredViews, declarations


class Number:
    """A declaration with a more specific kind below it."""


class Count(Number):
    """The more specific kind."""


class FieldWidget(DeclaredViews):
    """The family root: it shows nothing itself."""


class NumberWidget(FieldWidget, shows=(Number,)):
    pass


class CountWidget(NumberWidget, shows=(Count,)):
    pass


class StyledNumberWidget(NumberWidget):
    """A subclass declaring nothing shows nothing: its parent's declaration stays its parent's."""


def test_the_first_declaration_with_a_member_chooses_it():
    assert FieldWidget.showing(Count.__mro__) is CountWidget
    assert FieldWidget.showing(Number.__mro__) is NumberWidget


def test_a_class_shows_only_what_it_declares():
    assert StyledNumberWidget.shows == ()
    assert FieldWidget.shows == ()


def test_a_declaration_no_member_shows_is_refused():
    with pytest.raises(LookupError):
        FieldWidget.showing(str.__mro__)


class Prepared(DeclaredMetadata):
    """Metadata whose one instance names the kind that edits it."""

    def __init__(self, kind: type) -> None:
        self.kind = kind

    def declares(self):
        yield self.kind
        yield from super().declares()


def test_metadata_that_declares_more_is_read_through_its_own_declaration():
    annotation = Annotated[str, Prepared(Count)]
    assert FieldWidget.showing(declarations(annotation)) is CountWidget
    assert next(iter(declarations(Annotated[str, Number()]))) is Number


@pytest.mark.parametrize("value_type", (str, int, bool))
def test_documentation_does_not_replace_the_value_or_prepared_declaration(value_type):
    assert tuple(declarations(Annotated[value_type, "Field help"])) == tuple(declarations(value_type))
    annotation = Annotated[value_type, "Field help", Prepared(Count)]
    assert next(declarations(annotation)) is Count
    assert FieldWidget.showing(declarations(annotation)) is CountWidget


def test_a_family_asked_below_its_root_answers_from_its_own_tree():
    assert NumberWidget.showing(Count.__mro__) is CountWidget
    with pytest.raises(LookupError):
        CountWidget.showing(Number.__mro__)
