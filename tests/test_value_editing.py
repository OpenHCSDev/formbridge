"""ValueEditing and ControlConstruction own shared editing behavior."""

from formbridge.forms.value_editing import (
    ChoicesEditing,
    ControlConstruction,
    EnumEditing,
    LineEditing,
    MultilineEditing,
    OptionalEditing,
    SelectEditing,
    ValueEditing,
)


class FakeField:
    def __init__(self, value=None, default=None, annotation=str):
        self.value = value
        self.default = default
        self.has_default = default is not None
        self.placeholder = "(empty)"
        self.annotation = annotation
        self.label = "test"
        self.search_text = "test"

    def edit(self, value):
        self.value = value

    def validate(self, value):
        if not isinstance(value, str):
            raise TypeError("expected str")


class ConcreteEditor(ControlConstruction):
    def __init__(self, field):
        self._feedback = ""
        super().__init__(field)

    def display_feedback(self, text):
        self._feedback = text

    def clear_feedback(self):
        self._feedback = ""

    def bind_control(self):
        pass


def test_control_construction_binds_field_first():
    field = FakeField(value="hello")
    editor = ConcreteEditor(field)
    assert editor.field is field
    assert editor.field.value == "hello"


def test_value_text_uses_placeholder_for_none():
    field = FakeField(value=None)
    editor = ConcreteEditor(field)
    assert editor.value_text(None) == "(empty)"
    assert editor.value_text("hi") == "hi"


def test_default_note_shows_default():
    field = FakeField(default="fallback")
    editor = ConcreteEditor(field)
    assert "fallback" in editor.default_note()


def test_default_note_empty_without_default():
    field = FakeField()
    editor = ConcreteEditor(field)
    assert editor.default_note() == ""


def test_send_edits_field():
    field = FakeField(value="old")
    editor = ConcreteEditor(field)
    editor.send("new")
    assert field.value == "new"
    assert editor._feedback == ""


def test_send_refuses_on_error():
    field = FakeField()
    field.edit = lambda v: (_ for _ in ()).throw(ValueError("bad"))
    editor = ConcreteEditor(field)
    editor.send("bad")
    assert editor._feedback == "bad"


def test_multiline_editing_suppresses_default_note():
    class MultiEditor(MultilineEditing, ConcreteEditor):
        pass
    field = FakeField(default="long text")
    editor = MultiEditor(field)
    assert editor.default_note() == ""


def test_line_editing_acceptable():
    class LineEditor(LineEditing, ConcreteEditor):
        pass
    field = FakeField()
    editor = LineEditor(field)
    assert editor.acceptable("hello") is True


def test_finish_is_noop_by_default():
    field = FakeField()
    editor = ConcreteEditor(field)
    editor.finish()
