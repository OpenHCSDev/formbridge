"""The value a form edits, kept together with the value it shows."""

from __future__ import annotations

from dataclasses import dataclass, fields

from objectstate import DataclassFieldAccess
from objectstate.lazy_factory import get_base_type_for_lazy, replace_raw


@dataclass(frozen=True, slots=True)
class RawDisplayValue:
    """One dataclass value as edited (``raw``) and as shown (``display``).

    ``raw`` holds what this owner declares: an unset field is ``None`` there.
    ``display`` is the same value with inherited fields filled in. Keeping the
    two in one record keeps the question "did this owner supply the field, or
    was it inherited" answerable for every field (:meth:`shows_inherited`).
    """

    value_type: type
    raw: object
    display: object

    def __post_init__(self) -> None:
        raw_type = self._declared_type(self.raw)
        display_type = self._declared_type(self.display)
        if display_type is not raw_type:
            raise TypeError(
                f"Displayed value must be {raw_type.__name__}, "
                f"got {type(self.display).__name__}."
            )

    @classmethod
    def shown_as_edited(cls, value_type: type, raw: object) -> RawDisplayValue:
        """A value with nothing inherited: it is shown exactly as edited."""

        return cls(value_type, raw, raw)

    def _declared_type(self, value: object) -> type:
        declared = get_base_type_for_lazy(type(value)) or type(value)
        if not issubclass(declared, self.value_type):
            raise TypeError(
                f"Expected {self.value_type.__name__}, got {type(value).__name__}."
            )
        return declared

    @property
    def declared_type(self) -> type:
        """The concrete dataclass behind ``raw`` (its lazy wrapper removed)."""

        return self._declared_type(self.raw)

    def raw_field(self, field_name: str) -> object:
        """One edited field, read without resolving inherited values."""

        return DataclassFieldAccess.raw_value(self.raw, field_name)

    def display_field(self, field_name: str) -> object:
        """One shown field, read without resolving inherited values."""

        return DataclassFieldAccess.raw_value(self.display, field_name)

    def shows_inherited(self, field_name: str) -> bool:
        """Whether the shown field was inherited rather than declared here."""

        return (
            self.raw_field(field_name) is None
            and self.display_field(field_name) is not None
        )

    def field_default(self, field_name: str) -> object:
        """The declared default of one field of the concrete dataclass."""

        return next(
            item.default
            for item in fields(self.declared_type)
            if item.name == field_name
        )

    def replacing(self, **changes: object) -> RawDisplayValue:
        """The value after an edit: the fields change in both ``raw`` and ``display``."""

        return RawDisplayValue(
            self.value_type,
            replace_raw(self.raw, **changes),
            replace_raw(self.display, **changes),
        )

    def displaying(self, display: object) -> RawDisplayValue:
        """The same edited value shown with newly resolved inherited fields."""

        return RawDisplayValue(self.value_type, self.raw, display)
