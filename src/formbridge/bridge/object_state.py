"""ObjectState scope, field and code-document projections for the UI bridge."""

from __future__ import annotations

import hashlib
import logging
from collections.abc import Callable, Mapping, Sequence, Set
from dataclasses import dataclass, is_dataclass
from enum import Enum
from typing import ClassVar

from objectstate import ObjectState, ObjectStateRegistry
from objectstate.inspection import FieldInspection, type_name, type_qualname
from python_introspect import (
    JsonValue,
    UnifiedParameterAnalyzer,
    project_dataclass,
    to_jsonable,
)

from formbridge.bridge.contracts import (
    APPLY_TIME_TRAVEL_OPT_IN_GUARD,
    CONFIRMATION_REQUIRED_GUARD,
    STALE_CODE_DOCUMENT_REVISION_ERROR,
    SnapshotBackedUiCodeDocumentProviderABC,
    UiBridgeGuardPolicy,
    UiBridgeSnapshotProviderABC,
    UiCodeDocumentProviderIdentity,
    UiObjectStateScopeProviderABC,
    UiObjectStateScopeProviderIdentity,
)
from formbridge.bridge.dto import (
    AllFields,
    UiCatalogPageMetadata,
    UiCodeDocument,
    UiCodeDocumentApplyRequest,
    UiCodeDocumentApplyResult,
    UiCodeDocumentRequest,
    UiCodeDocumentSummary,
    UiCodeDocumentValidationRequest,
    UiCodeDocumentValidationResult,
    UiMutationReceipt,
    UiObjectStateFieldMutationRequest,
    UiObjectStateFieldMutationResult,
    UiObjectStateFieldProvenance,
    UiObjectStateFieldSemanticCarrier,
    UiObjectStateFieldSummary,
    UiObjectStateScopeCatalog,
    UiObjectStateScopeIdentity,
    UiObjectStateScopeListRequest,
    UiObjectStateScopeSummary,
    UiObjectStateValuePreview,
    UiSemanticAddress,
)
from formbridge.bridge.identities import UiStableWindowIdentityDeclaration
from formbridge.bridge.in_process import UiCodeDocumentApplyLabel
from formbridge.bridge.scope_policy import ObjectStateScopeVisibility
from formbridge.contracts import SCHEMA_VERSION, AgentError
from formbridge.forms.parameter_form_service import ParameterFormService
from formbridge.services.window_code_document import PYTHON_MIME_TYPE

OBJECT_STATE_SCOPE_PROVIDER_ID = "object_state.scopes"
OBJECT_STATE_SCOPE_CODE_DOCUMENT_ID = "object_state_scope"
OBJECT_STATE_SCOPE_CODE_DOCUMENT_PREFIX = f"{OBJECT_STATE_SCOPE_CODE_DOCUMENT_ID}:"
WINDOW_CODE_DOCUMENT_ID = "window_code_document"
WINDOW_CODE_DOCUMENT_PREFIX = f"{WINDOW_CODE_DOCUMENT_ID}:"
OBJECT_STATE_FIELD_PAGE_LIMIT_MAX = 1000
OBJECT_STATE_FIELD_VALUE_REPR_LIMIT = 500
OBJECT_STATE_FIELD_VALUE_PREVIEW_LIMIT = 160
OBJECT_STATE_FIELD_VALUE_PREVIEW_ITEMS = 4

logger = logging.getLogger(__name__)


def agent_object_state_scope_id(scope_id: str | None) -> str | None:
    """Return the stable agent-facing id for an ObjectState registry scope."""

    if scope_id is None:
        return None
    return UiStableWindowIdentityDeclaration.window_id_for_manager_scope(scope_id)


@dataclass(frozen=True, slots=True)
class ObjectStateScopeCodeDocumentAddress:
    """Nominal code-document address for one ObjectState scope."""

    scope_id: str

    prefix: ClassVar[str] = OBJECT_STATE_SCOPE_CODE_DOCUMENT_PREFIX
    minimum_scope_id_length: ClassVar[int] = 1

    @classmethod
    def parse(cls, document_id: str) -> ObjectStateScopeCodeDocumentAddress:
        if not document_id.startswith(cls.prefix):
            raise ValueError(
                "ObjectState scope code document ids must start with "
                f"{cls.prefix!r}; got {document_id!r}."
            )
        scope_id = document_id[len(cls.prefix) :]
        if len(scope_id) < cls.minimum_scope_id_length:
            raise ValueError("ObjectState scope code document id is missing a scope id.")
        return cls(scope_id=scope_id)

    @property
    def document_id(self) -> str:
        return f"{self.prefix}{self.scope_id}"

    @property
    def revision_key(self) -> str:
        return f"ui-code-document:{self.document_id}"

    def provider_identity(self, title: str) -> UiCodeDocumentProviderIdentity:
        return UiCodeDocumentProviderIdentity(
            document_id=self.document_id,
            widget_id=OBJECT_STATE_SCOPE_CODE_DOCUMENT_ID,
            title=title,
        )


@dataclass(frozen=True, slots=True)
class WindowCodeDocumentAddress:
    """Nominal code-document address for one open WindowManager code mode."""

    window_id: str

    prefix: ClassVar[str] = WINDOW_CODE_DOCUMENT_PREFIX

    @classmethod
    def parse(cls, document_id: str) -> WindowCodeDocumentAddress:
        if not document_id.startswith(cls.prefix):
            raise ValueError(
                f"Window code-document ids must start with {cls.prefix!r}; got {document_id!r}."
            )
        window_id = document_id[len(cls.prefix) :]
        if not window_id:
            raise ValueError("Window code-document id is missing a window id.")
        return cls(window_id=window_id)

    @classmethod
    def from_scope_id(cls, scope_id: str) -> WindowCodeDocumentAddress:
        return cls(
            window_id=UiStableWindowIdentityDeclaration.window_id_for_manager_scope(scope_id)
        )

    @property
    def document_id(self) -> str:
        return f"{self.prefix}{self.window_id}"

    @property
    def revision_key(self) -> str:
        return f"ui-code-document:{self.document_id}"

    def provider_identity(self, title: str) -> UiCodeDocumentProviderIdentity:
        return UiCodeDocumentProviderIdentity(
            document_id=self.document_id,
            widget_id=self.window_id,
            title=title,
        )


@dataclass(frozen=True, slots=True)
class ObjectStateFieldSemanticProjection(FieldInspection):
    """One inspected ObjectState field projected onto the bridge's DTOs."""

    @property
    def raw_json_value(self) -> JsonValue:
        return self.json_value(self.raw_value)

    @property
    def resolved_json_value(self) -> JsonValue | None:
        if not self.resolved_value_available:
            return None
        return self.json_value(self.resolved_value)

    @property
    def raw_value_preview(self) -> UiObjectStateValuePreview:
        return self.value_preview(self.raw_value)

    @property
    def resolved_value_preview(self) -> UiObjectStateValuePreview | None:
        if not self.resolved_value_available:
            return None
        return self.value_preview(self.resolved_value)

    def semantic_address(self, *, window_id: str | None = None) -> UiSemanticAddress:
        return UiSemanticAddress(
            object_state_scope_id=self.agent_scope_id,
            field_path=self.field_path,
            window_id=window_id,
        )

    @property
    def agent_scope_id(self) -> str:
        return agent_object_state_scope_id(self.state.scope_id) or self.state.scope_id

    def to_semantic_carrier(
        self,
        *,
        include_values: bool = False,
    ) -> UiObjectStateFieldSemanticCarrier:
        """Project the shared DTO semantics owned by this live field."""

        return UiObjectStateFieldSemanticCarrier(
            dirty=self.dirty,
            signature_diff=self.signature_diff,
            last_changed=self.last_changed,
            semantic_markers=self.semantic_markers,
            raw_value=self.raw_json_value if include_values else None,
            resolved_value=self.resolved_json_value if include_values else None,
            raw_value_preview=self.raw_value_preview,
            resolved_value_preview=self.resolved_value_preview,
            raw_value_is_none=self.raw_value_is_none,
            resolved_value_is_none=self.resolved_value_is_none,
            inherited_value=self.inherited_value,
            provenance=self.provenance_dto,
        )

    def to_field_summary(
        self,
        *,
        include_values: bool = False,
        include_description: bool = False,
    ) -> UiObjectStateFieldSummary:
        parameter_description = None
        if include_description:
            parameter_description = self.state.parameter_descriptions.get(self.field_path)
        return project_dataclass(
            UiObjectStateFieldSummary,
            self.to_semantic_carrier(include_values=include_values),
            schema_version=SCHEMA_VERSION,
            address=self.semantic_address(
                window_id=UiStableWindowIdentityDeclaration.window_id_for_manager_scope(
                    self.state.scope_id
                ),
            ),
            field_name=self.field_name,
            container_path=self.container_path,
            object_state_path_type=self.declaring_type,
            raw_value_type=self.raw_value_type,
            resolved_value_type=self.resolved_value_type,
            parameter_description=parameter_description,
        )

    @property
    def provenance_dto(self) -> UiObjectStateFieldProvenance | None:
        if self.provenance is None:
            return None
        return UiObjectStateFieldProvenance(
            source_scope_id=agent_object_state_scope_id(self.provenance.source_scope_id),
            source_type=type_qualname(self.provenance.source_type),
            source_field_path=self.provenance.source_field_path,
        )

    @staticmethod
    def json_value(value) -> JsonValue:
        try:
            return to_jsonable(value)
        except TypeError:
            value_repr = repr(value)
            if len(value_repr) > OBJECT_STATE_FIELD_VALUE_REPR_LIMIT:
                value_repr = f"{value_repr[:OBJECT_STATE_FIELD_VALUE_REPR_LIMIT]}...<truncated>"
            return value_repr

    @classmethod
    def value_preview(cls, value) -> UiObjectStateValuePreview:
        text, truncated = cls.preview_text(value)
        return UiObjectStateValuePreview(
            type_name=type_name(value),
            is_none=value is None,
            text=text,
            truncated=truncated,
        )

    @classmethod
    def preview_text(cls, value) -> tuple[str, bool]:
        text = cls._preview_text_unbounded(value)
        truncated = len(text) > OBJECT_STATE_FIELD_VALUE_PREVIEW_LIMIT
        if truncated:
            text = f"{text[:OBJECT_STATE_FIELD_VALUE_PREVIEW_LIMIT]}...<truncated>"
        return text, truncated

    @classmethod
    def _preview_text_unbounded(cls, value) -> str:
        if value is None:
            return "None"
        if callable(value):
            return cls._callable_preview_text(value)
        if isinstance(value, Enum):
            return f"{type(value).__name__}.{value.name}"
        if isinstance(value, str):
            return repr(value)
        if isinstance(value, bytes):
            return f"bytes(len={len(value)})"
        if isinstance(value, Mapping):
            keys = tuple(cls._preview_item_text(key) for key in cls._first_items(value.keys()))
            return f"{type(value).__name__}(len={len(value)}, keys={keys!r})"
        if isinstance(value, (Sequence, Set)) and not isinstance(
            value,
            (str, bytes, bytearray),
        ):
            items = tuple(cls._preview_item_text(item) for item in cls._first_items(value))
            return f"{type(value).__name__}(len={len(value)}, items={items!r})"
        if is_dataclass(value) and not isinstance(value, type):
            return repr(value)
        return repr(value)

    @staticmethod
    def _first_items(values) -> tuple[object, ...]:
        items = []
        for item in values:
            items.append(item)
            if len(items) >= OBJECT_STATE_FIELD_VALUE_PREVIEW_ITEMS:
                break
        return tuple(items)

    @staticmethod
    def _preview_item_text(value) -> str:
        if callable(value):
            return ObjectStateFieldSemanticProjection._callable_preview_text(value)
        if isinstance(value, Enum):
            return f"{type(value).__name__}.{value.name}"
        return repr(value)

    @staticmethod
    def _callable_preview_text(value: Callable[..., object]) -> str:
        try:
            payload = to_jsonable(value)
        except TypeError:
            return repr(value)
        if not isinstance(payload, Mapping):
            return repr(value)
        import_path = payload.get("import_path")
        if not isinstance(import_path, str):
            return repr(value)
        return import_path


class ObjectStateScopeProjectionService:
    """Project ObjectState registry entries into bounded agent DTOs."""

    def catalog(
        self,
        request: UiObjectStateScopeListRequest,
    ) -> UiObjectStateScopeCatalog:
        visibility = ObjectStateScopeVisibility(request)
        scopes = tuple(
            self.summary(state, request)
            for state in ObjectStateRegistry.get_all()
            if visibility.includes_scope_id(state.scope_id)
        )
        return UiObjectStateScopeCatalog(
            schema_version=SCHEMA_VERSION,
            object_state_token=ObjectStateRegistry.get_token(),
            current_branch=ObjectStateRegistry.get_current_branch(),
            current_snapshot_index=ObjectStateRegistry.get_current_snapshot_index(),
            active=ObjectStateRegistry.is_time_traveling(),
            scopes=scopes,
        )

    def summary(
        self,
        state: ObjectState,
        request: UiObjectStateScopeListRequest,
    ) -> UiObjectStateScopeSummary:
        fields, field_page = self._field_page(state, request)
        return UiObjectStateScopeSummary(
            schema_version=SCHEMA_VERSION,
            identity=UiObjectStateScopeIdentity(
                object_state_scope_id=agent_object_state_scope_id(state.scope_id) or state.scope_id,
            ),
            object_type=type(state.object_instance).__name__,
            parameter_count=len(state.parameters),
            dirty_field_count=len(state.dirty_fields),
            signature_diff_field_count=len(state.signature_diff_fields),
            has_unsaved_changes=bool(state.dirty_fields),
            has_default_overrides=bool(state.signature_diff_fields),
            last_changed_field=state.last_changed_field,
            fields=fields,
            field_page=field_page,
        )

    def _field_page(
        self,
        state: ObjectState,
        request: UiObjectStateScopeListRequest,
    ) -> tuple[tuple[UiObjectStateFieldSummary, ...], UiCatalogPageMetadata | None]:
        if not request.include_fields:
            return (), None

        if request.field_paths:
            all_field_paths = tuple(
                field_path for field_path in request.field_paths if field_path in state.parameters
            )
        else:
            all_field_paths = tuple(sorted(state.parameters.keys()))
        if request.field_filter is not AllFields:
            all_field_paths = tuple(
                field_path
                for field_path in all_field_paths
                if request.field_filter.matches(
                    self._field_summary(
                        state,
                        field_path,
                        include_values=False,
                        include_description=False,
                    ),
                )
            )
        offset = max(0, request.field_offset)
        limit = min(max(0, request.field_limit), OBJECT_STATE_FIELD_PAGE_LIMIT_MAX)
        selected_paths = all_field_paths[offset : offset + limit]
        next_offset = offset + len(selected_paths)
        truncated = next_offset < len(all_field_paths)
        next_page_offset = None
        if truncated:
            next_page_offset = next_offset
        page = UiCatalogPageMetadata(
            limit=limit,
            offset=offset,
            returned_count=len(selected_paths),
            total_count=len(all_field_paths),
            truncated=truncated,
            next_offset=next_page_offset,
        )
        fields = tuple(
            self._field_summary(
                state,
                field_path,
                include_values=request.include_field_values,
                include_description=request.include_field_descriptions,
            )
            for field_path in selected_paths
        )
        return fields, page

    def _field_summary(
        self,
        state: ObjectState,
        field_path: str,
        *,
        include_values: bool,
        include_description: bool,
    ) -> UiObjectStateFieldSummary:
        return ObjectStateFieldSemanticProjection.of(
            state,
            field_path,
        ).to_field_summary(
            include_values=include_values,
            include_description=include_description,
        )


def object_state_for_agent_scope_id(scope_id: str) -> ObjectState | None:
    """The ObjectState an agent-facing scope or window id names."""
    for candidate_scope_id in UiStableWindowIdentityDeclaration.manager_scopes_for_window_id(
        scope_id
    ):
        state = ObjectStateRegistry.get_by_scope(candidate_scope_id)
        if state is not None:
            return state
    return None


class ObjectStateFieldMutationService:
    """Mutate one ObjectState field through ObjectState's own update/reset API."""

    def __init__(
        self,
        before_mutation: Callable[[str], None] | None = None,
    ) -> None:
        self._before_mutation = before_mutation

    def mutate(
        self,
        request: UiObjectStateFieldMutationRequest,
    ) -> UiObjectStateFieldMutationResult:
        state = object_state_for_agent_scope_id(request.object_state_scope_id)
        if state is None:
            return self._error_result(
                request,
                AgentError(
                    code="ui_object_state_scope_not_found",
                    message=(
                        "ObjectState scope is not registered in the running UI: "
                        f"{request.object_state_scope_id!r}"
                    ),
                ),
            )
        if request.field_path not in state.parameters:
            return self._error_result(
                request,
                AgentError(
                    code="ui_object_state_field_not_found",
                    message=(
                        f"ObjectState field is not registered on this scope: {request.field_path!r}"
                    ),
                ),
            )

        before = self._field_summary(state, request)
        try:
            if self._before_mutation is not None:
                self._before_mutation(request.object_state_scope_id)
            if request.reset:
                state.reset_parameter(request.field_path)
            else:
                state.update_parameter(
                    request.field_path,
                    self._converted_value(state, request),
                )
            after = self._field_summary(state, request)
            return UiObjectStateFieldMutationResult(
                schema_version=SCHEMA_VERSION,
                address=after.address,
                mutated=True,
                reset=request.reset,
                receipt=UiMutationReceipt.accepted_for(request.request_token),
                before=before,
                after=after,
            )
        except Exception as exc:
            return self._error_result(
                request,
                AgentError.from_exception("ui_object_state_field_mutation_failed", exc),
                before=before,
            )

    @staticmethod
    def _field_summary(
        state: ObjectState,
        request: UiObjectStateFieldMutationRequest,
    ) -> UiObjectStateFieldSummary:
        return ObjectStateFieldSemanticProjection.of(
            state,
            request.field_path,
        ).to_field_summary(include_values=request.include_field_values)

    @staticmethod
    def _converted_value(
        state: ObjectState,
        request: UiObjectStateFieldMutationRequest,
    ) -> object:
        help_target = state.type_for_path(request.field_path)
        parameter_name = request.field_path.rsplit(".", 1)[-1]
        parameter_info = UnifiedParameterAnalyzer.analyze(help_target).get(parameter_name)
        if parameter_info is None:
            return request.value
        return ParameterFormService().convert_value_to_type(
            request.value,
            parameter_info.param_type,
            parameter_name,
            help_target,
        )

    @staticmethod
    def _error_result(
        request: UiObjectStateFieldMutationRequest,
        error: AgentError,
        *,
        before: UiObjectStateFieldSummary | None = None,
    ) -> UiObjectStateFieldMutationResult:
        return UiObjectStateFieldMutationResult(
            schema_version=SCHEMA_VERSION,
            address=UiSemanticAddress(
                object_state_scope_id=request.object_state_scope_id,
                field_path=request.field_path,
                window_id=request.window_id,
            ),
            mutated=False,
            reset=request.reset,
            receipt=UiMutationReceipt.rejected_for(request.request_token),
            before=before,
            errors=(error,),
        )


class ObjectStateScopeProvider(UiObjectStateScopeProviderABC):
    """ObjectState scope catalog provider."""

    identity = UiObjectStateScopeProviderIdentity(
        provider_id=OBJECT_STATE_SCOPE_PROVIDER_ID,
        title="ObjectState scopes",
    )

    def __init__(self) -> None:
        self._projection = ObjectStateScopeProjectionService()

    def catalog(
        self,
        request: UiObjectStateScopeListRequest,
    ) -> UiObjectStateScopeCatalog:
        return self._projection.catalog(request)


class WindowCodeDocumentDriverBackedProvider(SnapshotBackedUiCodeDocumentProviderABC):
    """Shared provider flow for WindowCodeDocumentDriver-backed documents."""

    def __init__(self, snapshot_provider: UiBridgeSnapshotProviderABC) -> None:
        self._snapshot_provider = snapshot_provider

    def read(self, request: UiCodeDocumentRequest) -> UiCodeDocument:
        try:
            address = self._address(request.document_id)
            driver = self._driver(address)
            document = driver.read_document(clean=request.clean)
            source_bytes = document.source.encode("utf-8")
            summary = self._summary_for_address(address, document.title)
            return UiCodeDocument(
                schema_version=SCHEMA_VERSION,
                summary=summary,
                source=document.source,
                mime_type=document.mime_type,
                size_bytes=len(source_bytes),
                sha256=hashlib.sha256(source_bytes).hexdigest(),
                current_revision_token=self._current_revision_token(address),
                current_snapshot=self._snapshot_provider.current_snapshot(),
                selection_mode=request.selection_mode,
                selected_scope_ids=self._selected_scope_ids(address),
            )
        except Exception as exc:
            return self._document_error(
                request,
                AgentError.from_exception("ui_code_document_read_failed", exc),
            )

    def validate(
        self,
        request: UiCodeDocumentValidationRequest,
    ) -> UiCodeDocumentValidationResult:
        try:
            address = self._address(request.document_id)
            self._driver(address).validate_source(request.source)
            return UiCodeDocumentValidationResult(
                schema_version=SCHEMA_VERSION,
                document_id=request.document_id,
                valid=True,
                normalized_scope_ids=self._selected_scope_ids(address),
            )
        except Exception as exc:
            return UiCodeDocumentValidationResult(
                schema_version=SCHEMA_VERSION,
                document_id=request.document_id,
                valid=False,
                errors=(AgentError.from_exception("ui_code_document_validation_failed", exc),),
            )

    def apply(self, request: UiCodeDocumentApplyRequest) -> UiCodeDocumentApplyResult:
        guard_error = self._apply_guard_policy(request).first_error()
        if guard_error is not None:
            return self._apply_error(request, guard_error)

        try:
            address = self._address(request.document_id)
            current_revision = self._current_revision_token(address)
            if request.base_revision_token != current_revision:
                return self._apply_error(
                    request,
                    STALE_CODE_DOCUMENT_REVISION_ERROR,
                )

            driver = self._driver(address)
            if not driver.writable():
                return self._apply_error(
                    request,
                    AgentError(
                        code="ui_code_document_read_only",
                        message="The UI code document is currently read-only.",
                    ),
                )
            current_document = driver.read_document(clean=True)
            current_source = current_document.source
            if driver.source_is_current(
                request.source,
                current_document=current_document,
            ):
                return self._apply_unchanged(request)
            driver.validate_source(request.source)
            ObjectStateRegistry.ensure_baseline_snapshot()
            pre_snapshot = self._snapshot_provider.current_snapshot()
            pre_head_id = self._snapshot_provider.current_branch_head_snapshot_id()
            label = UiCodeDocumentApplyLabel.resolve(
                request,
                self._provider_identity_for_label(address),
            ).value
            with ObjectStateRegistry.atomic_success(
                label,
                self._mutation_scope_id(address),
            ):
                self._before_apply(address)
                driver.apply_source(request.source)

            post_head_id = self._snapshot_provider.current_branch_head_snapshot_id()
            if driver.records_object_state_snapshot_on_apply() and post_head_id == pre_head_id:
                if driver.read_document(clean=True).source == current_source:
                    return self._apply_unchanged(request)
                return self._apply_error(
                    request,
                    AgentError(
                        code="snapshot_not_recorded",
                        message=(
                            "Applying the UI document did not record a new ObjectState snapshot."
                        ),
                    ),
                )

            post_snapshot = self._snapshot_provider.current_snapshot()
            new_revision_token = self._current_revision_token(address)
            return UiCodeDocumentApplyResult(
                schema_version=SCHEMA_VERSION,
                document_id=request.document_id,
                applied=True,
                base_revision_token=request.base_revision_token,
                receipt=UiMutationReceipt.accepted_for(request.request_token),
                outcome="applied",
                new_revision_token=new_revision_token,
                current_revision_token=new_revision_token,
                current_snapshot=post_snapshot,
                undo_snapshot=pre_snapshot,
                pre_apply_snapshot=pre_snapshot,
                post_apply_snapshot=post_snapshot,
            )
        except Exception as exc:
            logger.exception(
                "Failed to apply UI code document %s",
                request.document_id,
            )
            return self._apply_error(
                request,
                AgentError.from_exception("ui_code_document_apply_failed", exc),
            )

    @staticmethod
    def _apply_guard_policy(
        request: UiCodeDocumentApplyRequest,
    ) -> UiBridgeGuardPolicy:
        return UiBridgeGuardPolicy(
            rules=(
                CONFIRMATION_REQUIRED_GUARD.bind(
                    lambda: request.confirmation_is_required(),
                ),
                APPLY_TIME_TRAVEL_OPT_IN_GUARD.bind(
                    lambda: (
                        ObjectStateRegistry.is_time_traveling()
                        and not request.apply_if_time_traveling
                    ),
                ),
            )
        )

    def _address(self, document_id: str):
        raise NotImplementedError

    def _before_apply(self, address) -> None:
        del address

    def _driver(self, address):
        raise NotImplementedError

    def _summary_for_address(self, address, title: str) -> UiCodeDocumentSummary:
        raise NotImplementedError

    def _selected_scope_ids(self, address) -> tuple[str, ...]:
        raise NotImplementedError

    def _revision_key_for_address(self, address) -> str:
        raise NotImplementedError

    def _provider_identity_for_label(self, address) -> UiCodeDocumentProviderIdentity:
        raise NotImplementedError

    def _mutation_scope_id(self, address) -> str:
        raise NotImplementedError

    def _current_revision_token_for_apply_result(
        self,
        request: UiCodeDocumentApplyRequest,
    ) -> str | None:
        try:
            address = self._address(request.document_id)
            return self._current_revision_token(address)
        except Exception:
            return super()._current_revision_token_for_apply_result(request)

    def _current_revision_token(
        self,
        address,
    ) -> str:
        return self._snapshot_provider.revision_token(self._revision_key_for_address(address))

    def _document_error(
        self,
        request: UiCodeDocumentRequest,
        error: AgentError,
    ) -> UiCodeDocument:
        source_bytes = b""
        return UiCodeDocument(
            schema_version=SCHEMA_VERSION,
            summary=self.summary(),
            source="",
            mime_type=PYTHON_MIME_TYPE,
            size_bytes=0,
            sha256=hashlib.sha256(source_bytes).hexdigest(),
            current_revision_token=self._snapshot_provider.revision_token(
                self.identity.revision_key
            ),
            current_snapshot=self._snapshot_provider.current_snapshot(),
            selection_mode=request.selection_mode,
            selected_scope_ids=(),
            errors=(error,),
        )
