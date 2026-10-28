"""Fields of an ObjectState as their declarations describe them, for every UI backend.

A backend draws a form by walking `DeclaredField`s and choosing one of its own
widget classes for each through a `DeclaredViews` family. Everything a field
says about itself (label, help, default, kind, bounds, choices, page) is read
here from the dataclass declaration, so no backend restates it.
"""

from __future__ import annotations

from collections.abc import Callable, Iterable, Iterator
from dataclasses import dataclass, fields, is_dataclass
from functools import cached_property
from inspect import cleandoc
from typing import Annotated, ClassVar, Optional, Self, TypeVar, get_args, get_origin

from annotated_types import Interval
from objectstate import DottedFieldPath, ObjectState
from python_introspect import (
    ParameterInfo,
    UnifiedParameterAnalyzer,
    declared_field_label,
    optional_member_type,
    resolve_annotated,
    resolve_optional,
)
from python_introspect.validation import validate_annotation_value

from formbridge.forms.ui_utils import FieldDisplayText

Metadata = TypeVar("Metadata")

BOUND_SYMBOLS = (("gt", ">"), ("ge", ">="), ("lt", "<"), ("le", "<="))
"""How each `annotated_types.Interval` bound reads."""


@dataclass(frozen=True)
class Placeholder:
    """Text for an empty field, not an offered or persisted value."""

    text: str


@dataclass(frozen=True)
class Multiline:
    """Text of several lines: `Annotated[str, Multiline()]`."""


@dataclass(frozen=True, eq=False)
class FormPage:
    """One page (tab) of a form, named on the top-level fields shown on it.

    `Annotated[Appearance, INTERFACE]` puts that group on the page `INTERFACE`.
    A page is one object declared once; the pages of a form and their order
    follow from the fields that name them.
    """

    title: str


class DeclaredViews:
    """A family of widget classes, each registered under what it shows.

    A class directly below this one starts a family. A member names the
    declarations it shows in its own body (`shows = (int,)`), so adding a kind
    of field is adding a class: nothing lists the members and nothing chooses
    between them by testing types. A backend's field widgets and editors are
    such families.
    """

    shows: ClassVar[tuple[object, ...]] = ()
    shown_by: ClassVar[dict[object, Callable]]

    def __init_subclass__(cls, **kwargs: object) -> None:
        super().__init_subclass__(**kwargs)
        if DeclaredViews in cls.__bases__:
            cls.shown_by = {}
        for declaration in vars(cls).get("shows", ()):
            cls.shown_by[declaration] = cls

    @classmethod
    def showing(cls, declarations: Iterable[object]) -> Callable[..., Self]:
        """The member registered under the first of these declarations that has one."""
        declarations = tuple(declarations)
        for declaration in declarations:
            if declaration in cls.shown_by:
                return cls.shown_by[declaration]
        raise LookupError(f"No {cls.__name__} shows any of {declarations!r}")


def declarations(annotation: object) -> Iterator[object]:
    """What an annotation declares, most specific first.

    `Annotated` metadata comes before the type it annotates, `T | None` is
    `Optional`, and a class is followed by its bases.
    """
    if get_origin(annotation) is Annotated:
        base, *metadata = get_args(annotation)
        for item in metadata:
            yield from type(item).__mro__[:-1]
        yield from declarations(base)
    elif optional_member_type(annotation) is not None:
        yield Optional
    else:
        declared = get_origin(annotation) or annotation
        yield from declared.__mro__[:-1] if isinstance(declared, type) else (declared,)


@dataclass(frozen=True)
class DeclaredField:
    """One field of an ObjectState: where its value lives and how it was declared."""

    state: ObjectState
    path: DottedFieldPath

    @property
    def declaration(self) -> ParameterInfo:
        return self.state.parameter_structure.declarations[self.path.value]

    @property
    def annotation(self) -> object:
        return self.declaration.param_type

    @property
    def owner_type(self) -> type:
        """The class of the resolved record containing this field.

        ObjectState's declaration owner may instead be a function. Record
        serialization needs the containing value's actual class, including
        the delegate returned by to_object at the root.
        """
        parent = self.path.parent.value
        owner = self.state.get_resolved_value(parent) if parent else self.state.to_object()
        return type(owner)

    def metadata(self, kind: type[Metadata]) -> Metadata | None:
        """Metadata of the bound field, including an optional member's metadata."""
        return next(self.all_metadata(kind), None)

    def all_metadata(self, kind: type[Metadata]) -> Iterator[Metadata]:
        """Every item of this kind the field and its optional member declare, outermost first."""
        for annotation in (self.annotation, resolve_optional(resolve_annotated(self.annotation))):
            if get_origin(annotation) is Annotated:
                for item in get_args(annotation)[1:]:
                    if isinstance(item, kind):
                        yield item

    @property
    def interval(self) -> Interval:
        """The declared bounds (`Ge`, `Gt`, `Le`, `Lt`, `Interval`) merged into one interval.

        Each bound is read by its `Interval` field name, so every annotated_types
        bound class and `Interval` itself contribute without a list of classes.
        """
        bounds = {field.name for field in fields(Interval)}
        return Interval(**{
            field.name: getattr(item, field.name)
            for item in self.all_metadata(object) if is_dataclass(item)
            for field in fields(item) if field.name in bounds
        })

    @property
    def bounds_text(self) -> str:
        """The declared bounds as a reader would say them: `>= 1, <= 10`; empty when unbounded."""
        interval = self.interval
        return ", ".join(
            f"{symbol} {getattr(interval, name)}"
            for name, symbol in BOUND_SYMBOLS if getattr(interval, name) is not None
        )

    @property
    def value(self) -> object:
        return self.state.get_resolved_value(self.path.value)

    @property
    def default(self) -> object:
        return self.declaration.default_value

    @property
    def has_default(self) -> bool:
        return not self.declaration.is_required

    @property
    def placeholder(self) -> str:
        hint = self.metadata(Placeholder)
        return hint.text if hint is not None else ""

    @property
    def label(self) -> str:
        return (
            declared_field_label(self.annotation)
            or FieldDisplayText.from_field_name(self.declaration.name).display_name
        )

    @property
    def help(self) -> str:
        return cleandoc(self.declaration.description or "")

    @cached_property
    def search_text(self) -> str:
        """What a search over the form matches: this label and every enclosing group's."""
        return " ".join(
            DeclaredField(self.state, step).label
            for step in self.state.parameter_structure.ancestors(self.path)
        ).lower()

    @property
    def member(self) -> DeclaredField:
        """The same field as declared without `None`."""
        return OptionalMemberField(self.state, self.path)

    def validate(self, value: object) -> None:
        """Require this field's declared type and constraints before edit or save."""
        # ObjectState takes any value for a field of the root object and only
        # fails later, when the object is rebuilt (ObjectState issue #47).
        validate_annotation_value(self.annotation, value, path=self.label)

    def edit(self, value: object) -> None:
        """Give the field a value accepted by its declaration."""
        self.validate(value)
        self.state.update_parameter(self.path.value, value)


class OptionalMemberField(DeclaredField):
    """The member editor reads a narrower annotation, not a copied declaration."""

    @property
    def annotation(self) -> object:
        return optional_member_type(resolve_annotated(super().annotation))


def form_pages(
    state: ObjectState, shown: Iterable[DottedFieldPath]
) -> dict[FormPage, tuple[DottedFieldPath, ...]]:
    """The pages of a form and the top-level fields on each, in declaration order.

    Every shown top-level field of a paged form names its page; a form whose
    fields name none is one page with no title.
    """
    pages: dict[FormPage | None, list[DottedFieldPath]] = {}
    for path in shown:
        page = DeclaredField(state, path).metadata(FormPage)
        pages.setdefault(page, []).append(path)
    if None in pages and len(pages) > 1:
        unpaged = ", ".join(path.value for path in pages[None])
        raise TypeError(f"Top-level fields {unpaged} name no FormPage beside fields that do")
    return {page or FormPage(""): tuple(paths) for page, paths in pages.items()}


class FieldPath:
    """One field of a dataclass tree: `FieldPath(Settings).sidebar.hide`.

    Each step is checked against the dataclass fields when the path is built,
    so a path that exists names a declared field. `str(path)` is the dotted
    name ObjectState keeps the field under.
    """

    __slots__ = ("_root", "_names")

    def __init__(self, root: type, names: tuple[str, ...] = ()) -> None:
        self._root, self._names = root, names

    def __getattr__(self, name: str) -> FieldPath:
        owner = declared_type(self)
        if not is_dataclass(owner) or name not in {field.name for field in fields(owner)}:
            raise AttributeError(f"{owner!r} declares no field {name!r}")
        return FieldPath(self._root, (*self._names, name))

    def __str__(self) -> str:
        return ".".join(self._names)

    def __repr__(self) -> str:
        return f"FieldPath({self._root.__name__}, {str(self)!r})"

    def __eq__(self, other: object) -> bool:
        return (
            isinstance(other, FieldPath)
            and (self._root, self._names) == (other._root, other._names)
        )

    def __hash__(self) -> int:
        return hash((self._root, self._names))

    def bind(self, state: ObjectState) -> DeclaredField:
        """Bind this declaration to the field ObjectState declares at this path."""
        if not issubclass(state.type_for_path(""), self._root):
            raise TypeError(f"{self!r} does not name a field of this ObjectState")
        return DeclaredField(state, state.parameter_structure.path(str(self)))

    def matches(self, field: DeclaredField) -> bool:
        """Whether this declaration names the bound field, including its root type."""
        return (
            issubclass(field.state.type_for_path(""), self._root)
            and field.path.parts == self._names
        )


def parent(path: FieldPath) -> FieldPath:
    return FieldPath(path._root, path._names[:-1])


def declared_annotation(path: FieldPath) -> object:
    """The field's annotation as written, `Annotated` metadata included."""
    if not path._names:
        return path._root
    return UnifiedParameterAnalyzer.analyze(declared_type(parent(path)))[
        path._names[-1]
    ].param_type


def declared_type(path: FieldPath) -> object:
    """The type a value of the field has, without `Annotated` and `Optional`."""
    return resolve_annotated(resolve_optional(resolve_annotated(declared_annotation(path))))
