"""Key declarations independent of any UI toolkit: which command a key invokes, under which
input mode, with its title and summary, and which native key a binding was declared on.
A toolkit projects these into its own bindings."""

from __future__ import annotations

import inspect
import re
from abc import ABC, ABCMeta, abstractmethod
from dataclasses import dataclass
from typing import Callable, ClassVar, Generic, Iterator, TypeVar

NodeT = TypeVar("NodeT", contravariant=True)


class InputMode:
    """Which input mode keys are declared under; a toolkit's editing engine subclasses it."""

    modal = False

    @classmethod
    def navigation_spellings(cls, key: type[NavigationKey]) -> tuple[str, ...]:
        return (key.key,)


class ModalInputMode(InputMode):
    """An input mode whose keys are commands until a key enters text."""

    modal = True

    @classmethod
    def navigation_spellings(cls, key: type[NavigationKey]) -> tuple[str, ...]:
        return (*super().navigation_spellings(key), key.modal)


class KeyDeclarationType(ABCMeta):
    """A key-declaring class, including declarations supplied by a metaclass."""

    def permits_key_overlap(cls, other: KeyDeclarationType) -> bool:
        """An explicitly declared alternative may share this declaration's key."""
        return False


class KeyInvocation(ABC):
    """The concrete command a binding invokes, independent of its active mode."""

    @staticmethod
    def qualified(declaration: type | Callable[..., object]) -> str:
        return f"{declaration.__module__}.{declaration.__qualname__}"

    @abstractmethod
    def key_identity(self) -> str: ...

    @abstractmethod
    def key_title(self) -> str: ...

    @abstractmethod
    def key_summary(self) -> str: ...

    @abstractmethod
    def key_system(self) -> bool: ...

    def binding_identity(self, mode: type[InputMode]) -> str:
        return self.in_mode(self.key_identity(), mode)

    @staticmethod
    def in_mode(identity: str, mode: type) -> str:
        return f"{identity}:{KeyInvocation.qualified(mode)}"

    def visible_for_focus(self, focused: bool) -> bool:
        """Local commands follow their declaration's actual prior-focus membership."""
        return focused

    def permits_invocation_overlap(self, other: KeyInvocation) -> bool:
        return False

    def overlaps_declaration(self, other: KeyDeclarationType) -> bool:
        return False


class KeyTitle:
    """Human text derived from the declaration rather than a second title roster."""

    def __get__(self, instance: object, owner: type[KeyDeclaration]) -> str:
        return owner.default_title()


class KeyDeclaration(KeyInvocation, Generic[NodeT], metaclass=KeyDeclarationType):
    """Shared metadata for application actions and native editor commands.

    Each provider retains its existing family registry. This view discovers the
    provider declarations through inheritance; no menu supplies their names.
    """

    title = KeyTitle()
    system: ClassVar[bool] = False
    _declared: ClassVar[list[type[KeyDeclaration]]] = []

    def __init_subclass__(cls, **kwargs) -> None:
        super().__init_subclass__(**kwargs)
        KeyDeclaration._declared.append(cls)

    @classmethod
    def default_title(cls) -> str:
        return re.sub(r"(?<=[a-z0-9])(?=[A-Z])", " ", cls.__name__).capitalize()

    @classmethod
    def identity(cls) -> str:
        return cls.qualified(cls)

    @classmethod
    def binding_id(cls, mode: type) -> str:
        return cls.binding_id_for(cls, mode)

    @staticmethod
    def binding_id_for(declaration: type | Callable[..., object], mode: type) -> str:
        """Class and native callable declarations use the same mode-qualified identity."""
        return KeyInvocation.in_mode(KeyInvocation.qualified(declaration), mode)

    def key_identity(self) -> str:
        return type(self).identity()

    def key_title(self) -> str:
        return self.title

    def key_summary(self) -> str:
        return self.summary()

    def key_system(self) -> bool:
        return self.system

    def permits_invocation_overlap(self, other: KeyInvocation) -> bool:
        return other.overlaps_declaration(type(self))

    def overlaps_declaration(self, other: KeyDeclarationType) -> bool:
        return type(self).permits_key_overlap(other)

    @abstractmethod
    def __call__(self, node: NodeT) -> object: ...

    @classmethod
    def summary(cls) -> str:
        return inspect.cleandoc(cls.__doc__ or "")

    @classmethod
    def declarations(cls) -> Iterator[type[KeyDeclaration]]:
        """Project each key family from the declaration owner's registry."""
        return (member for member in KeyDeclaration._declared
                if issubclass(member, cls) and not inspect.isabstract(member))


@dataclass(frozen=True)
class DeclaredKey:
    """A decoded native input identity, distinct from its configured spelling."""

    def decoded(self, key: str) -> DeclaredKey:
        return self

    def spellings(self, mode: type[InputMode], spelling: str) -> tuple[str, ...]:
        return (spelling,)

    def invocations(self, defaults: tuple[KeyInvocation, ...]) -> tuple[KeyInvocation, ...]:
        return defaults

    def preempts(self, printable_outside_text: bool) -> bool:
        """Whether a printable key, pressed where it is not literal text, runs this binding
        before type-to-search sees it."""
        return False

    def input_bindings(self, spelling: str) -> tuple[tuple[str, str], ...]:
        """Native input aliases for an external editing engine."""
        return ()


class UndecodedKey(DeclaredKey):
    """Only Binding.make_bindings sees an external declaration's key spelling."""

    def decoded(self, key: str) -> DeclaredKey:
        return NavigationKey.from_key(key)


class NavigationKey(DeclaredKey, KeyInvocation):
    """One preference for an arrow, independent of the focused control's effect.

    Bindings keep their native callable, availability and order. Only the saved
    input identity is shared: configuring Up must not mean configuring TextArea,
    a table, a tree and every future arrow control separately.
    """

    key: ClassVar[str]
    modal: ClassVar[str]
    _by_key: ClassVar[dict[str, type[NavigationKey]]] = {}

    def __init_subclass__(cls, *, key: str, modal: str, **kwargs: object) -> None:
        super().__init_subclass__(**kwargs)
        cls.key = key
        cls.modal = modal
        cls._by_key[key] = cls

    @classmethod
    def from_key(cls, key: str) -> DeclaredKey:
        """Decode a declared native key once, before any preference changes it."""
        try:
            declaration = cls._by_key[key]
        except KeyError:
            return DeclaredKey()
        return declaration()

    def invocations(self, defaults: tuple[KeyInvocation, ...]) -> tuple[KeyInvocation, ...]:
        return (self,)

    def spellings(self, mode: type[InputMode], spelling: str) -> tuple[str, ...]:
        return mode.navigation_spellings(type(self))

    def preempts(self, printable_outside_text: bool) -> bool:
        """Arrow aliases precede search, never the target's literal text input."""
        return printable_outside_text

    def key_identity(self) -> str:
        return self.qualified(type(self))

    def input_bindings(self, spelling: str) -> tuple[tuple[str, str], ...]:
        return ((spelling, self.key),)

    def key_title(self) -> str:
        return f"Cursor {self.key}"

    def key_summary(self) -> str:
        return f"Use these keys wherever the focused control handles {self.key}."

    def key_system(self) -> bool:
        return False

    def visible_for_focus(self, focused: bool) -> bool:
        """Global arrow preferences remain editable even from a non-arrow focus."""
        return True


class UpKey(NavigationKey, key="up", modal="k"):
    pass


class DownKey(NavigationKey, key="down", modal="j"):
    pass


class LeftKey(NavigationKey, key="left", modal="h"):
    pass


class RightKey(NavigationKey, key="right", modal="l"):
    pass
