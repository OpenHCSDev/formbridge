"""Live UI overview state-surface provider."""

from __future__ import annotations

import hashlib
from dataclasses import replace

from objectstate.object_state import ObjectStateRegistry
from python_introspect import to_jsonable

from formbridge.bridge.contracts import (
    UiBridgeSnapshotProviderABC,
    UiLiveOverviewContributorIdentity,
    UiOwnedStateSurfaceDeclaration,
    UiStateSurfaceProviderABC,
    UiStateSurfaceProviderIdentity,
)
from formbridge.bridge.dto import (
    UiLiveOverviewItem,
    UiLiveOverviewSection,
    UiLiveOverviewSeverity,
    UiLiveOverviewState,
    UiStateSurfaceDocument,
    UiStateSurfaceRequest,
    UiStateSurfaceSummary,
)
from formbridge.bridge.registry import (
    UiBridgeSurfaceRegistry,
)
from formbridge.contracts import SCHEMA_VERSION, AgentError
from formbridge.selection import AllItems


class UiLiveOverviewStateSurfaceProvider(UiStateSurfaceProviderABC):
    """Pollable UI overview assembled from registered provider contributions."""

    def __init__(
        self,
        *,
        registry: UiBridgeSurfaceRegistry,
        snapshot_provider: UiBridgeSnapshotProviderABC,
        declaration: UiOwnedStateSurfaceDeclaration,
        identity: UiStateSurfaceProviderIdentity,
    ) -> None:
        self._registry = registry
        self._snapshot_provider = snapshot_provider
        self._declaration = declaration
        self.identity = identity

    def summary(self) -> UiStateSurfaceSummary:
        return UiStateSurfaceSummary(
            schema_version=SCHEMA_VERSION,
            identity=self.identity.as_surface_identity(),
            title=self.identity.title,
            widget_id=self.identity.widget_id,
            readable=True,
            supported_selection_modes=(AllItems.name,),
            current_selection_count=0,
            total_scope_count=1,
        )

    def read(self, request: UiStateSurfaceRequest) -> UiStateSurfaceDocument:
        selection_mode = request.resolved_selection_mode(AllItems)
        try:
            state = UiLiveOverviewState(
                schema_version=SCHEMA_VERSION,
                summary=self.summary(),
                object_state_token=ObjectStateRegistry.get_token(),
                sections=self._sections(),
                selected_scope_ids=(),
                current_revision_token=self._snapshot_provider.revision_token(
                    self.identity.revision_key
                ),
                current_snapshot=self._snapshot_provider.current_snapshot(),
            )
        except Exception as exc:
            return self._state_error(
                request,
                (AgentError.from_exception("ui_state_surface_read_failed", exc),),
            )
        revision_token = self._revision_token(state, selection_mode=selection_mode)
        state = replace(
            state,
            current_revision_token=revision_token,
            current_snapshot=self._snapshot_provider.current_snapshot(),
            unchanged=request.base_revision_token == revision_token,
        )
        return self._document_from_state(state, selection_mode=selection_mode)

    def _sections(self) -> tuple[UiLiveOverviewSection, ...]:
        sections: list[UiLiveOverviewSection] = []
        for provider in self._registry.overview_contributors():
            try:
                sections.extend(provider.overview_sections())
            except Exception as exc:
                sections.append(self._provider_error_section(provider.overview_identity, exc))
        return tuple(sections)

    @staticmethod
    def _provider_error_section(
        identity: UiLiveOverviewContributorIdentity,
        exc: Exception,
    ) -> UiLiveOverviewSection:
        error = AgentError.from_exception("ui_live_overview_provider_failed", exc)
        return UiLiveOverviewSection(
            section_id=identity.section_id,
            title=identity.title,
            summary="overview unavailable",
            items=(
                UiLiveOverviewItem(
                    label=error.code,
                    status=error.exception_type,
                    detail=error.message,
                    severity=UiLiveOverviewSeverity.ERROR.value,
                ),
            ),
        )

    def _revision_token(
        self,
        state: UiLiveOverviewState,
        *,
        selection_mode: str,
    ) -> str:
        parts = (
            self.identity.revision_key,
            str(state.object_state_token),
            self._snapshot_provider.current_branch_head_snapshot_id(),
            str(ObjectStateRegistry.get_current_snapshot_index()),
            selection_mode,
            state.sections,
        )
        return hashlib.sha256(repr(parts).encode("utf-8")).hexdigest()

    def _state_error(
        self,
        request: UiStateSurfaceRequest,
        errors: tuple[AgentError, ...],
    ) -> UiStateSurfaceDocument:
        selection_mode = request.resolved_selection_mode(AllItems)
        state = UiLiveOverviewState(
            schema_version=SCHEMA_VERSION,
            summary=self.summary(),
            object_state_token=ObjectStateRegistry.get_token(),
            sections=(),
            selected_scope_ids=(),
            current_revision_token=self._snapshot_provider.revision_token(
                self.identity.revision_key
            ),
            current_snapshot=self._snapshot_provider.current_snapshot(),
            errors=errors,
        )
        return self._document_from_state(state, selection_mode=selection_mode)

    def _document_from_state(
        self,
        state: UiLiveOverviewState,
        *,
        selection_mode: str,
    ) -> UiStateSurfaceDocument:
        payload = to_jsonable(state)
        if not isinstance(payload, dict):
            raise TypeError("Live overview payload did not serialize to an object.")
        return UiStateSurfaceDocument(
            schema_version=state.schema_version,
            summary=state.summary,
            payload_schema=self._declaration.payload_schema,
            payload=payload,
            current_revision_token=state.current_revision_token,
            current_snapshot=state.current_snapshot,
            selection_mode=selection_mode,
            selected_scope_ids=state.selected_scope_ids,
            unchanged=state.unchanged,
            warnings=state.warnings,
            errors=state.errors,
        )
