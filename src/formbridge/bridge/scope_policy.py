"""ObjectState scope visibility policy shared by UI bridge projections."""

from __future__ import annotations

from abc import ABC
from dataclasses import dataclass, field
from typing import ClassVar

from metaclass_registry import AutoRegisterMeta

from formbridge.bridge.dto import UiObjectStateScopeVisibility
from formbridge.bridge.identities import UiStableWindowIdentityDeclaration


class HiddenObjectStateScope(ABC, metaclass=AutoRegisterMeta):
    """A system ObjectState scope agents see only when they ask for system scopes.

    Applications declare each of their system scopes as a subclass.
    """

    __registry_key__ = "scope_id"
    __skip_if_no_key__ = True

    scope_id: ClassVar[str | None] = None


@dataclass(frozen=True, slots=True)
class ObjectStateScopeVisibility:
    """Agent-facing visibility policy for ObjectState scope ids."""

    request: UiObjectStateScopeVisibility = field(default_factory=UiObjectStateScopeVisibility)

    def includes_system_scopes(self) -> bool:
        return self.request.include_system_scopes

    def includes_scope_id(self, scope_id: str) -> bool:
        if self.includes_system_scopes() or self.has_agent_alias(scope_id):
            return True
        return scope_id not in HiddenObjectStateScope.__registry__

    @staticmethod
    def has_agent_alias(scope_id: str) -> bool:
        return UiStableWindowIdentityDeclaration.window_id_for_manager_scope(scope_id) != scope_id
