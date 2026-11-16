"""Which list and scroll commands exist: each command's default keys, the native key it was
declared on, and the operation it asks of the control. A toolkit projects the commands into
its own bindings and implements the operations on its controls."""
from __future__ import annotations

from abc import abstractmethod
from typing import ClassVar

from formbridge.key_declarations import (
    DeclaredKey,
    DownKey,
    KeyDeclaration,
    LeftKey,
    RightKey,
    UndecodedKey,
    UpKey,
)


class NavigationTarget:
    """A control that answers navigation commands: each command's operation runs on it."""

    @property
    def accepts_navigation(self) -> bool:
        return True

    def apply_navigation(self, command: NavigationCommand) -> object:
        return command.apply(self)


class NavigationCommand(KeyDeclaration[NavigationTarget]):
    """A list command owns its keys; controls own the operation it requests."""

    keys: ClassVar[tuple[str, ...]] = ()
    declared_key: ClassVar[DeclaredKey] = UndecodedKey()

    @staticmethod
    def available(node: NavigationTarget) -> bool:
        return node.accepts_navigation

    def __call__(self, node: NavigationTarget) -> object:
        return node.apply_navigation(self)

    @abstractmethod
    def apply(self, node: NavigationTarget) -> object: ...


class CursorCommand(NavigationCommand):
    """Move the selected row of the focused list.

    Not a priority binding: priority resolves from the App inward, so a list
    nested in another (a Select overlay in a ListView) lost its arrows to the
    outer one. Type-to-search consumes printable keys only; printable cursor
    aliases precede it through NavigationKey.preempts.
    """


class VerticalCursorCommand(CursorCommand):
    """Move within a vertical selection without claiming horizontal keys."""


class HorizontalCursorCommand(CursorCommand):
    """Step a horizontal selection using the same cursor priority."""


class CursorLeft(HorizontalCursorCommand):
    keys = ("left",)
    declared_key = LeftKey()

    def apply(self, node: NavigationTarget) -> object:
        return node.action_cursor_left()


class CursorRight(HorizontalCursorCommand):
    keys = ("right",)
    declared_key = RightKey()

    def apply(self, node: NavigationTarget) -> object:
        return node.action_cursor_right()


class UpNavigation(NavigationCommand):
    declared_key = UpKey()

    def apply(self, node):
        return node.action_cursor_up()


class DownNavigation(NavigationCommand):
    declared_key = DownKey()

    def apply(self, node):
        return node.action_cursor_down()


class CursorUp(UpNavigation, VerticalCursorCommand):
    keys = ("up",)


class CursorDown(DownNavigation, VerticalCursorCommand):
    keys = ("down",)


class ListCommand(NavigationCommand):
    """Navigation through a list's ends and pages."""


class SelectionCommand(NavigationCommand):
    """Activate the native control's current selection."""

    def apply(self, node):
        return node.action_select_cursor()


class SelectCursor(SelectionCommand, ListCommand):
    keys = ("enter",)


class ActivateSelection(SelectionCommand):
    keys = ("space",)


class FirstNavigation(NavigationCommand):
    def apply(self, node):
        return node.action_first()


class LastNavigation(NavigationCommand):
    def apply(self, node):
        return node.action_last()


class First(FirstNavigation, ListCommand):
    keys = ("home",)


class Last(LastNavigation, ListCommand):
    keys = ("end",)


class ScrollCommand(NavigationCommand):
    """A key a scrolling view answers by moving its viewport."""


class ScrollUp(ScrollCommand):
    keys = ("up",)

    def apply(self, node: NavigationTarget) -> object:
        return node.action_scroll_up()


class ScrollDown(ScrollCommand):
    keys = ("down",)

    def apply(self, node: NavigationTarget) -> object:
        return node.action_scroll_down()


class ScrollLeft(ScrollCommand):
    keys = ("left",)

    def apply(self, node: NavigationTarget) -> object:
        return node.action_scroll_left()


class ScrollRight(ScrollCommand):
    keys = ("right",)

    def apply(self, node: NavigationTarget) -> object:
        return node.action_scroll_right()


class ScrollHome(ScrollCommand):
    keys = ("home",)

    def apply(self, node: NavigationTarget) -> object:
        return node.action_scroll_home()


class ScrollEnd(ScrollCommand):
    keys = ("end",)

    def apply(self, node: NavigationTarget) -> object:
        return node.action_scroll_end()


class PageUp(ListCommand, ScrollCommand):
    """A list's page and a view's page are one key and one operation."""

    keys = ("pageup",)

    def apply(self, node):
        return node.action_page_up()


class PageDown(ListCommand, ScrollCommand):
    keys = ("pagedown",)

    def apply(self, node):
        return node.action_page_down()


class PageLeft(ScrollCommand):
    keys = ("ctrl+pageup",)

    def apply(self, node: NavigationTarget) -> object:
        return node.action_page_left()


class PageRight(ScrollCommand):
    keys = ("ctrl+pagedown",)

    def apply(self, node: NavigationTarget) -> object:
        return node.action_page_right()
