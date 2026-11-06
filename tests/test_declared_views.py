"""A view family is the inheritance tree below it; each class declares what it shows."""

import pytest

from formbridge.forms.declared_fields import DeclaredViews


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


def test_a_family_asked_below_its_root_answers_from_its_own_tree():
    assert NumberWidget.showing(Count.__mro__) is CountWidget
    with pytest.raises(LookupError):
        CountWidget.showing(Number.__mro__)
