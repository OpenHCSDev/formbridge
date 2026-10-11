"""Registered identities for stable agent-facing UI bridge objects."""

from __future__ import annotations

from abc import ABC
from typing import ClassVar

from metaclass_registry import AutoRegisterMeta


class UiBridgeIdentityDeclaration(ABC, metaclass=AutoRegisterMeta):
    """Registered identity for stable agent-facing UI bridge objects."""

    __registry_key__ = "value"
    __skip_if_no_key__ = True

    value: ClassVar[str | None] = None

    @classmethod
    def require_value(cls) -> str:
        if cls.value is None:
            raise ValueError(f"{cls.__name__} does not declare a bridge identity value.")
        return cls.value


class UiStableWindowIdentityDeclaration(UiBridgeIdentityDeclaration):
    """Registered identity and presentation for a stable public UI window."""

    title: ClassVar[str | None] = None
    manager_scope_alias: ClassVar[str | None] = None
    """Window-manager scope id this window is registered under, when it is not ``value``."""

    @staticmethod
    def window_id_for_manager_scope(manager_scope_id: str) -> str:
        """The agent-facing window id of one window-manager scope."""

        for declaration in UiStableWindowIdentityDeclaration.declaration_types():
            if declaration.manager_scope_alias == manager_scope_id:
                return declaration.require_value()
        return manager_scope_id

    @staticmethod
    def manager_scopes_for_window_id(window_id: str) -> tuple[str, ...]:
        """Every window-manager scope that may hold one agent-facing window."""

        aliases = tuple(
            declaration.manager_scope_alias
            for declaration in UiStableWindowIdentityDeclaration.declaration_types()
            if declaration.value == window_id
            and declaration.manager_scope_alias is not None
            and declaration.manager_scope_alias != window_id
        )
        return (window_id, *aliases)

    @staticmethod
    def manager_scope_for_window_id(window_id: str) -> str:
        """The window-manager scope one agent-facing window is opened under."""

        for declaration in UiStableWindowIdentityDeclaration.declaration_types():
            if declaration.value == window_id and declaration.manager_scope_alias is not None:
                return declaration.manager_scope_alias
        return window_id

    @classmethod
    def require_title(cls) -> str:
        """Return the declaration-owned public window title."""

        if cls.title is None:
            raise ValueError(f"{cls.__name__} does not declare a window title.")
        return cls.title

    @classmethod
    def has_title(cls) -> bool:
        return cls.title is not None

    @classmethod
    def declaration_types(
        cls,
    ) -> tuple[type[UiStableWindowIdentityDeclaration], ...]:
        """Project the complete stable-window family from the identity registry."""

        return tuple(
            dict.fromkeys(
                declaration
                for declaration in cls.__registry__.values()
                if issubclass(declaration, cls)
                and declaration.value is not None
                and declaration.has_title()
            )
        )


class UiWidgetIdentityDeclaration(UiBridgeIdentityDeclaration):
    """Registered widget identity declaration."""

    @classmethod
    def action_provider_id(cls) -> str:
        """Return the stable action-provider id for this widget."""
        return f"{cls.require_value()}.actions"


class UiStableWidgetIdentityDeclaration(
    UiWidgetIdentityDeclaration,
    UiStableWindowIdentityDeclaration,
):
    """Stable public window whose content is also a registered UI widget."""


class UiOwnedByWidgetIdentityDeclaration(UiBridgeIdentityDeclaration):
    """Identity declaration for a UI bridge object owned by one widget."""

    widget_identity: ClassVar[type[UiWidgetIdentityDeclaration] | None] = None

    @classmethod
    def widget_id(cls) -> str:
        if cls.widget_identity is None:
            raise ValueError(f"{cls.__name__} does not declare a widget identity.")
        return cls.widget_identity.require_value()


class UiCodeDocumentIdentityDeclaration(UiOwnedByWidgetIdentityDeclaration):
    """Registered code document identity declaration."""


class UiStateSurfaceIdentityDeclarationBase(UiBridgeIdentityDeclaration):
    """Registered protocol identity for one UI state surface.

    Widget ownership and presentation metadata live on the owning widget class.
    """


class ManagedWindowWidgetIdentity(UiWidgetIdentityDeclaration):
    value = "managed_window"


class UiLiveOverviewStateSurfaceIdentityDeclaration(UiStateSurfaceIdentityDeclarationBase):
    value = "ui_live_overview.state"
