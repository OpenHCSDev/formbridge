"""In-process side of the running-UI bridge: one ``@serves`` handler per wire operation."""

from __future__ import annotations

import datetime as _datetime
import hashlib
import threading
import time
import uuid
from collections.abc import Callable
from dataclasses import dataclass, replace
from functools import partial
from typing import TypeVar

from objectstate.object_state import ObjectStateRegistry
from python_introspect import project_dataclass, to_jsonable

from formbridge.bridge.application import UiBridgeApplication
from formbridge.bridge.contracts import (
    CONFIRMATION_REQUIRED_GUARD,
    RESTORE_TIME_TRAVEL_OPT_IN_GUARD,
    UiActionProviderABC,
    UiBridgeGuardPolicy,
    UiBridgeSnapshotProviderABC,
    UiCodeDocumentProviderABC,
    UiLiveOverviewContributorABC,
    UiLiveOverviewContributorIdentity,
    UiObjectStateScopeProviderABC,
    UiStateSurfaceProviderABC,
    UiWindowProviderABC,
)
from formbridge.bridge.dto import (
    UNKNOWN_UI_BRIDGE_OPERATION_ROUTE,
    ActionRejected,
    OperationCompleted,
    OperationFailed,
    OperationNotFound,
    OperationRunning,
    OperationUnavailable,
    UiActionCatalog,
    UiActionIdentity,
    UiActionInvokeRequest,
    UiActionInvokeResult,
    UiBranchCatalog,
    UiBranchRef,
    UiBranchSwitchRequest,
    UiBridgeConnectionSpec,
    UiBridgeOperationIdentity,
    UiBridgeOperationRef,
    UiBridgeOperationRoute,
    UiBridgeOperationStatus,
    UiBridgeOperationStatusRequest,
    UiBridgeStatus,
    UiCodeDocument,
    UiCodeDocumentApplyRequest,
    UiCodeDocumentApplyResult,
    UiCodeDocumentCatalog,
    UiCodeDocumentIdentity,
    UiCodeDocumentRequest,
    UiCodeDocumentValidationRequest,
    UiCodeDocumentValidationResult,
    UiLiveOverviewItem,
    UiLiveOverviewMetric,
    UiLiveOverviewSection,
    UiLiveOverviewSeverity,
    UiMutationReceipt,
    UiMutationRequestToken,
    UiObjectStateFieldMutationRequest,
    UiObjectStateFieldMutationResult,
    UiObjectStateScopeCatalog,
    UiObjectStateScopeListRequest,
    UiObjectStateScopeVisibility,
    UiSnapshotCatalog,
    UiSnapshotListRequest,
    UiSnapshotRef,
    UiSnapshotRestoreRequest,
    UiSnapshotRestoreResult,
    UiStateSurfaceCatalog,
    UiStateSurfaceDocument,
    UiStateSurfaceRequest,
    UiTimeTravelHeadRequest,
    UiWidgetActionInvokeRequest,
    UiWidgetActionInvokeResult,
    UiWidgetTreeRequest,
    UiWidgetTreeResult,
    UiWindowCatalog,
    UiWindowCloseRequest,
    UiWindowCloseResult,
    UiWindowFocusRequest,
    UiWindowFocusResult,
    UiWindowNavigateRequest,
    UiWindowNavigateResult,
    UiWindowSnapshotRequest,
    UiWindowSnapshotResult,
)
from formbridge.bridge.registry import (
    UiBridgeProviderSetABC,
    UiBridgeRegistrationContext,
    UiBridgeSurfaceRegistry,
)
from formbridge.bridge.scope_policy import ObjectStateScopeVisibility
from formbridge.bridge.service import (
    UiBridgeApplyDocumentOperation,
    UiBridgeCloseWindowOperation,
    UiBridgeFocusWindowOperation,
    UiBridgeGatewayABC,
    UiBridgeGetDocumentOperation,
    UiBridgeGetOperationStatusOperation,
    UiBridgeGetStateSurfaceOperation,
    UiBridgeInvokeActionOperation,
    UiBridgeInvokeWidgetActionOperation,
    UiBridgeListActionsOperation,
    UiBridgeListBranchesOperation,
    UiBridgeListDocumentsOperation,
    UiBridgeListObjectStateScopesOperation,
    UiBridgeListSnapshotsOperation,
    UiBridgeListStateSurfacesOperation,
    UiBridgeListWindowsOperation,
    UiBridgeMutateObjectStateFieldOperation,
    UiBridgeNavigateWindowOperation,
    UiBridgeOperation,
    UiBridgeOperationServer,
    UiBridgeRestoreSnapshotOperation,
    UiBridgeSnapshotWindowOperation,
    UiBridgeStatusOperation,
    UiBridgeSwitchBranchOperation,
    UiBridgeTimeTravelHeadOperation,
    UiBridgeValidateDocumentOperation,
    UiBridgeWidgetTreeOperation,
    serves,
)
from formbridge.contracts import SCHEMA_VERSION, AgentError, AgentResultEnvelope, AgentWarning
from formbridge.services.main_thread_dispatch import MainThreadDispatcher

UiBridgeObservedResultT = TypeVar("UiBridgeObservedResultT", bound=AgentResultEnvelope)


@dataclass(slots=True)
class UiCodeDocumentValidationError(ValueError):
    errors: tuple[AgentError, ...]

    def __str__(self) -> str:
        return "; ".join(error.message for error in self.errors)


class UiBridgeBusyError(RuntimeError):
    """Raised when a mutating UI bridge operation is already running."""


class UiBridgeMutationGate:
    """Serialize mutating bridge operations for one running UI."""

    def __init__(self, tracker: UiBridgeOperationTracker) -> None:
        self._lock = threading.Lock()
        self._tracker = tracker

    def run(
        self,
        *,
        operation_type: type[UiBridgeOperation],
        target_id: str | None,
        callback: Callable[
            [UiBridgeOperationRef],
            AgentResultEnvelope,
        ],
    ):
        operation = self.begin(operation_type=operation_type, target_id=target_id)
        try:
            result = callback(operation)
            self.complete(operation, operation_type, result)
            return result
        except Exception as exc:
            self.fail(operation, exc)
            raise

    def begin(
        self,
        *,
        operation_type: type[UiBridgeOperation],
        target_id: str | None,
    ) -> UiBridgeOperationRef:
        """Start one serialized mutation and return its pollable operation ref."""
        if not self._lock.acquire(blocking=False):
            raise UiBridgeBusyError("A mutating UI bridge operation is already running.")
        return self._tracker.start(operation_type.require_name(), target_id)

    def complete(
        self,
        operation: UiBridgeOperationRef,
        operation_type: type[UiBridgeOperation],
        result: AgentResultEnvelope,
    ) -> None:
        """Complete a mutation successfully and release the mutation gate."""
        try:
            self._tracker.complete(
                operation.identity.operation_id,
                status=OperationCompleted,
                outcome=operation_type.outcome(result),
                errors=result.errors,
                warnings=result.warnings,
            )
        finally:
            self._lock.release()

    def fail(
        self,
        operation: UiBridgeOperationRef,
        exception: Exception,
    ) -> None:
        """Complete a mutation as failed and release the mutation gate."""
        try:
            self._tracker.complete(
                operation.identity.operation_id,
                status=OperationFailed,
                outcome="error",
                errors=(AgentError.from_exception("ui_bridge_operation_failed", exception),),
            )
        finally:
            self._lock.release()


class UiBridgeOperationTracker(UiLiveOverviewContributorABC):
    """In-memory operation status projection for bridge calls."""

    overview_identity = UiLiveOverviewContributorIdentity(
        section_id="ui-bridge-operations",
        title="UI bridge operations",
    )

    def __init__(self) -> None:
        self._operations: dict[str, UiBridgeOperationRef] = {}
        self._lock = threading.Lock()

    def start(self, operation_name: str, target_id: str | None) -> UiBridgeOperationRef:
        operation_id = str(uuid.uuid4())
        operation = UiBridgeOperationRef(
            schema_version=SCHEMA_VERSION,
            identity=UiBridgeOperationIdentity(
                operation_id=operation_id,
                route=UiBridgeOperationRoute(
                    operation_name=operation_name,
                    target_id=target_id,
                ),
            ),
            status=OperationRunning.name,
            started_at_unix=time.time(),
        )
        with self._lock:
            self._operations[operation_id] = operation
        return operation

    def complete(
        self,
        operation_id: str,
        *,
        status: type[UiBridgeOperationStatus],
        outcome: str | None,
        errors: tuple[AgentError, ...] = (),
        warnings: tuple[AgentWarning, ...] = (),
        result: AgentResultEnvelope | None = None,
    ) -> UiBridgeOperationRef:
        with self._lock:
            operation = self._operations[operation_id]
            completed = replace(
                operation,
                status=status.name,
                completed_at_unix=time.time(),
                outcome=outcome,
                errors=errors,
                warnings=warnings,
                result_payload=None if result is None else to_jsonable(result),
            )
            self._operations[operation_id] = completed
        return completed

    def complete_result(
        self, operation_id: str, result: AgentResultEnvelope
    ) -> UiBridgeOperationRef:
        """Project one typed completion through its registered declaration owner."""
        operation = self.get(operation_id)
        contract = UiBridgeOperation.for_name(operation.identity.operation_name)
        if not isinstance(result, contract.result_type):
            raise TypeError(
                f"{contract.require_name()} requires {contract.result_type.__qualname__}."
            )
        return self.complete(
            operation_id,
            status=(OperationFailed if result.errors else OperationCompleted),
            outcome="error" if result.errors else contract.success_outcome,
            errors=result.errors,
            warnings=result.warnings,
            result=result,
        )

    def fail_exception(self, operation_id: str, error: Exception) -> UiBridgeOperationRef:
        operation = self.get(operation_id)
        contract = UiBridgeOperation.for_name(operation.identity.operation_name)
        return self.complete(
            operation_id,
            status=OperationFailed,
            outcome="error",
            errors=(AgentError.from_exception(contract.failure_error_code, error),),
        )

    def observe(
        self,
        contract: type[UiBridgeOperation],
        target_id: str,
        invoke: Callable[[Callable[[UiBridgeObservedResultT], None]], UiBridgeObservedResultT],
    ) -> tuple[UiBridgeOperationRef, UiBridgeObservedResultT]:
        """Use this tracker for one asynchronously completed typed operation."""
        operation = self.start(contract.require_name(), target_id)
        try:
            result = invoke(partial(self.complete_result, operation.identity.operation_id))
            if (
                result.errors
                and self.get(operation.identity.operation_id).completed_at_unix is None
            ):
                self.complete_result(operation.identity.operation_id, result)
        except Exception as exc:
            self.fail_exception(operation.identity.operation_id, exc)
            raise
        return operation, result

    def get(self, operation_id: str) -> UiBridgeOperationRef:
        with self._lock:
            if operation_id in self._operations:
                return self._operations[operation_id]
        return UiBridgeOperationRef(
            schema_version=SCHEMA_VERSION,
            identity=UiBridgeOperationIdentity(
                operation_id=operation_id,
                route=UNKNOWN_UI_BRIDGE_OPERATION_ROUTE,
            ),
            status=OperationNotFound.name,
            started_at_unix=0.0,
            completed_at_unix=0.0,
            outcome="not_found",
            errors=(
                AgentError(
                    code="unknown_ui_bridge_operation",
                    message=f"Unknown UI bridge operation: {operation_id}",
                ),
            ),
        )

    def operations(self) -> tuple[UiBridgeOperationRef, ...]:
        with self._lock:
            return tuple(self._operations.values())

    def overview_sections(self) -> tuple[UiLiveOverviewSection, ...]:
        operations = self.operations()
        status_counts = {
            status: sum(1 for operation in operations if operation.status == status.name)
            for status in (OperationRunning, OperationFailed, OperationCompleted)
        }
        recent_operations = tuple(reversed(operations[-5:]))
        return (
            UiLiveOverviewSection(
                section_id=self.overview_identity.section_id,
                title=self.overview_identity.title,
                summary=(
                    f"{status_counts[OperationRunning]} running, "
                    f"{status_counts[OperationFailed]} failed, "
                    f"{status_counts[OperationCompleted]} completed"
                ),
                metrics=(
                    UiLiveOverviewMetric(
                        key=OperationRunning.name,
                        label="Running",
                        value=str(status_counts[OperationRunning]),
                    ),
                    UiLiveOverviewMetric(
                        key=OperationFailed.name,
                        label="Failed",
                        value=str(status_counts[OperationFailed]),
                    ),
                    UiLiveOverviewMetric(
                        key=OperationCompleted.name,
                        label="Completed",
                        value=str(status_counts[OperationCompleted]),
                    ),
                ),
                items=tuple(
                    UiLiveOverviewItem(
                        label=operation.identity.operation_name,
                        status=operation.status,
                        detail=self._operation_detail(operation),
                        severity=self._operation_severity(operation),
                    )
                    for operation in recent_operations
                ),
            ),
        )

    @staticmethod
    def _operation_status(
        operation: UiBridgeOperationRef,
    ) -> type[UiBridgeOperationStatus]:
        try:
            return UiBridgeOperationStatus.named(operation.status)
        except ValueError:
            return OperationUnavailable

    @classmethod
    def _operation_severity(cls, operation: UiBridgeOperationRef) -> str:
        if operation.errors:
            return UiLiveOverviewSeverity.ERROR.value
        if operation.warnings:
            return UiLiveOverviewSeverity.WARNING.value
        return cls._operation_status(operation).live_overview_severity

    @staticmethod
    def _operation_detail(operation: UiBridgeOperationRef) -> str:
        route = operation.identity.route
        if route.target_id is None:
            return operation.identity.operation_id
        return f"{route.target_id} ({operation.identity.operation_id})"


@dataclass(slots=True)
class UiBridgePostedMutation:
    """Completion box for a mutation that may run inline or on the Qt event loop."""

    result: AgentResultEnvelope | None = None
    error: Exception | None = None

    @property
    def completed(self) -> bool:
        return self.result is not None or self.error is not None

    def complete(self, result: AgentResultEnvelope) -> None:
        self.result = result

    def fail(self, error: Exception) -> None:
        self.error = error

    def require_result(self) -> AgentResultEnvelope:
        if self.error is not None:
            raise self.error
        if self.result is None:
            raise RuntimeError("Queued UI bridge mutation has not completed.")
        return self.result


class UiObjectStateSnapshotProvider(UiBridgeSnapshotProviderABC):
    """Typed projection and restore API for ObjectState history."""

    def __init__(
        self,
        before_restore: Callable[[], None] | None = None,
    ) -> None:
        self._before_restore = before_restore

    def list_snapshots(
        self,
        request: UiSnapshotListRequest,
    ) -> UiSnapshotCatalog:
        return self.catalog(request)

    def catalog(
        self,
        visibility_request: UiObjectStateScopeVisibility | None = None,
    ) -> UiSnapshotCatalog:
        visibility = ObjectStateScopeVisibility(
            visibility_request or UiObjectStateScopeVisibility()
        )
        history = ObjectStateRegistry.get_branch_history()
        current_branch = ObjectStateRegistry.get_current_branch()
        current_index = self.current_snapshot_index()
        refs = tuple(
            self._snapshot_ref(snapshot, index, history, visibility)
            for index, snapshot in enumerate(history)
            if visibility.includes_system_scopes() or self._visible_state_count(snapshot) > 0
        )
        return UiSnapshotCatalog(
            schema_version=SCHEMA_VERSION,
            current_branch=current_branch,
            current_snapshot_index=current_index,
            object_state_token=ObjectStateRegistry.get_token(),
            active=ObjectStateRegistry.is_time_traveling(),
            snapshots=refs,
            branches=self.branch_refs(),
        )

    def branch_refs(self) -> tuple[UiBranchRef, ...]:
        branches = []
        for branch in ObjectStateRegistry.list_branches():
            branches.append(
                UiBranchRef(
                    schema_version=SCHEMA_VERSION,
                    name=str(branch["name"]),
                    head_snapshot_id=str(branch["head_id"]),
                    base_snapshot_id=str(branch["base_id"]),
                    description=str(branch["description"]),
                    is_current=bool(branch["is_current"]),
                )
            )
        return tuple(branches)

    def current_snapshot(self) -> UiSnapshotRef | None:
        history = ObjectStateRegistry.get_branch_history()
        if not history:
            return None
        current_index = self.current_snapshot_index()
        if current_index == -1:
            return None
        return self._snapshot_ref(
            history[current_index],
            current_index,
            history,
            ObjectStateScopeVisibility(UiObjectStateScopeVisibility(include_system_scopes=True)),
        )

    def current_snapshot_index(self) -> int:
        current_index = ObjectStateRegistry.get_current_snapshot_index()
        if current_index != -1:
            return current_index
        history = ObjectStateRegistry.get_branch_history()
        if not history:
            return -1
        return len(history) - 1

    def current_branch_head_snapshot_id(self) -> str | None:
        history = ObjectStateRegistry.get_branch_history()
        if not history:
            return None
        return history[-1].id

    def revision_token(self, document_id: str) -> str:
        time_travel_active = ObjectStateRegistry.is_time_traveling()
        parts = (
            document_id,
            str(ObjectStateRegistry.get_token()),
            ObjectStateRegistry.get_current_branch(),
            str(self.current_branch_head_snapshot_id()),
            str(ObjectStateRegistry.get_current_snapshot_index()),
            str(time_travel_active),
        )
        return hashlib.sha256("|".join(parts).encode("utf-8")).hexdigest()

    def restore_snapshot(
        self,
        request: UiSnapshotRestoreRequest,
    ) -> UiSnapshotRestoreResult:
        guard_error = self._restore_guard_policy(request).first_error()
        if guard_error is not None:
            return self._restore_error(guard_error)

        target = self._target_snapshot(request)
        if target is None:
            return self._restore_error(
                AgentError(
                    code="snapshot_not_found",
                    message="Snapshot target was not found.",
                )
            )

        if request.snapshot_id is not None:
            operation = partial(
                ObjectStateRegistry.time_travel_to_snapshot,
                request.snapshot_id,
            )
        elif request.index is not None:
            operation = partial(
                ObjectStateRegistry.time_travel_to,
                request.index,
            )
        elif request.branch is not None:
            operation = partial(self._restore_branch_head, request.branch)
        else:
            operation = bool
        restored, restore_error = self._run_restore(operation)
        if restore_error is not None:
            return self._restore_error(restore_error)

        return UiSnapshotRestoreResult(
            schema_version=SCHEMA_VERSION,
            restored=restored,
            target_snapshot=target,
            current_snapshot=self.current_snapshot(),
            catalog=self.catalog(request),
        )

    def time_travel_head(
        self,
        request: UiTimeTravelHeadRequest,
    ) -> UiSnapshotRestoreResult:
        if request.confirmation_is_required():
            return self._restore_error(
                AgentError(
                    code="confirmation_required",
                    message="UI confirmation is required.",
                )
            )
        target = self.current_snapshot()
        restored, restore_error = self._run_restore(ObjectStateRegistry.time_travel_to_head)
        if restore_error is not None:
            return self._restore_error(restore_error)
        return UiSnapshotRestoreResult(
            schema_version=SCHEMA_VERSION,
            restored=restored,
            target_snapshot=target,
            current_snapshot=self.current_snapshot(),
            catalog=self.catalog(),
        )

    def switch_branch(
        self,
        request: UiBranchSwitchRequest,
    ) -> UiSnapshotRestoreResult:
        return self.restore_snapshot(request.as_restore_request())

    def _run_restore(
        self,
        operation: Callable[[], bool],
    ) -> tuple[bool, AgentError | None]:
        """Authorize and execute one ObjectState history mutation."""

        try:
            if self._before_restore is not None:
                self._before_restore()
            return bool(operation()), None
        except Exception as exc:
            return False, AgentError.from_exception(
                "ui_snapshot_restore_rejected",
                exc,
            )

    def _target_snapshot(
        self,
        request: UiSnapshotRestoreRequest,
    ) -> UiSnapshotRef | None:
        if request.snapshot_id is not None:
            return self._ref_for_snapshot_id(request.snapshot_id)
        if request.index is not None:
            history = ObjectStateRegistry.get_branch_history()
            if request.index < 0:
                index = len(history) + request.index
            else:
                index = request.index
            if 0 <= index < len(history):
                return self._snapshot_ref(
                    history[index],
                    index,
                    history,
                    ObjectStateScopeVisibility(
                        UiObjectStateScopeVisibility(include_system_scopes=True)
                    ),
                )
            return None
        if request.branch is not None:
            branches = {branch.name: branch for branch in self.branch_refs()}
            if request.branch not in branches:
                return None
            return self._ref_for_snapshot_id(
                branches[request.branch].head_snapshot_id,
                branch=request.branch,
            )
        return None

    def _restore_branch_head(self, branch: str) -> bool:
        known_branches = {ref.name for ref in self.branch_refs()}
        if branch not in known_branches:
            return False
        return ObjectStateRegistry.switch_branch(branch)

    def _ref_for_snapshot_id(
        self,
        snapshot_id: str,
        *,
        branch: str | None = None,
    ) -> UiSnapshotRef | None:
        history = ObjectStateRegistry.get_branch_history(branch)
        for index, snapshot in enumerate(history):
            if snapshot.id == snapshot_id:
                return self._snapshot_ref(
                    snapshot,
                    index,
                    history,
                    ObjectStateScopeVisibility(
                        UiObjectStateScopeVisibility(include_system_scopes=True)
                    ),
                )
        return None

    def _snapshot_ref(
        self,
        snapshot,
        index: int,
        history,
        visibility: ObjectStateScopeVisibility,
    ) -> UiSnapshotRef:
        current_index = ObjectStateRegistry.get_current_snapshot_index()
        head_index = len(history) - 1
        is_head = index == head_index
        is_current = (current_index == -1 and is_head) or current_index == index
        return UiSnapshotRef(
            schema_version=SCHEMA_VERSION,
            snapshot_id=snapshot.id,
            index=index,
            branch=ObjectStateRegistry.get_current_branch(),
            parent_snapshot_id=snapshot.parent_id,
            timestamp_unix=snapshot.timestamp,
            timestamp=_datetime.datetime.fromtimestamp(snapshot.timestamp).isoformat(
                timespec="milliseconds"
            ),
            label=snapshot.label or f"Snapshot #{index}",
            num_states=(
                len(snapshot.all_states)
                if visibility.includes_system_scopes()
                else self._visible_state_count(snapshot)
            ),
            is_current=is_current,
            is_head=is_head,
            uri=(
                f"{UiBridgeApplication.current().endpoint_application.identifier}"
                f"://ui/snapshots/{snapshot.id}"
            ),
        )

    @staticmethod
    def _visible_state_count(snapshot) -> int:
        visibility = ObjectStateScopeVisibility()
        return sum(1 for scope_id in snapshot.all_states if visibility.includes_scope_id(scope_id))

    @staticmethod
    def _restore_guard_policy(
        request: UiSnapshotRestoreRequest,
    ) -> UiBridgeGuardPolicy:
        return UiBridgeGuardPolicy(
            rules=(
                CONFIRMATION_REQUIRED_GUARD.bind(
                    lambda: request.confirmation_is_required(),
                ),
                RESTORE_TIME_TRAVEL_OPT_IN_GUARD.bind(
                    lambda: (
                        ObjectStateRegistry.is_time_traveling() and not request.allow_auto_branch
                    ),
                ),
            )
        )

    @staticmethod
    def _restore_error(error: AgentError) -> UiSnapshotRestoreResult:
        return UiSnapshotRestoreResult(
            schema_version=SCHEMA_VERSION,
            restored=False,
            target_snapshot=None,
            current_snapshot=None,
            catalog=None,
            errors=(error,),
        )


@dataclass(frozen=True, slots=True)
class UiCodeDocumentApplyLabel:
    """Formal defaulting authority for apply snapshot labels."""

    value: str

    @classmethod
    def resolve(
        cls,
        request: UiCodeDocumentApplyRequest,
        identity: UiCodeDocumentIdentity,
    ) -> UiCodeDocumentApplyLabel:
        if request.snapshot_label is not None:
            return cls(request.snapshot_label)
        return cls(identity.default_edit_label)


class UiAgentBridgeService(UiBridgeOperationServer):
    """In-process UI bridge owned by the running UI; applications subclass it.

    UI work runs on the owner thread through ``dispatcher``.
    """

    def __init__(
        self,
        *,
        dispatcher: MainThreadDispatcher,
        provider_set: UiBridgeProviderSetABC | None = None,
        registry: UiBridgeSurfaceRegistry | None = None,
        snapshot_provider: UiObjectStateSnapshotProvider | None = None,
        operation_tracker: UiBridgeOperationTracker | None = None,
        object_state_mutation_authorizer: Callable[[str], None] | None = None,
    ) -> None:
        self._dispatcher = dispatcher
        self._snapshot_provider = snapshot_provider or UiObjectStateSnapshotProvider()
        self._operation_tracker = operation_tracker or UiBridgeOperationTracker()
        self._mutation_gate = UiBridgeMutationGate(self._operation_tracker)
        self._object_state_mutation_authorizer = object_state_mutation_authorizer
        self._registry = registry or UiBridgeSurfaceRegistry()
        if provider_set is not None:
            provider_set.register(
                UiBridgeRegistrationContext(
                    registry=self._registry,
                    snapshot_provider=self._snapshot_provider,
                )
            )

    def close(self) -> None:
        """Fence callbacks queued by this bridge instance."""

        self._dispatcher.close()

    def register_provider(self, provider: UiCodeDocumentProviderABC) -> None:
        self._registry.register_code_document_provider(provider)

    def register_state_provider(self, provider: UiStateSurfaceProviderABC) -> None:
        self._registry.register_state_surface_provider(provider)

    def register_action_provider(self, provider: UiActionProviderABC) -> None:
        self._registry.register_action_provider(provider)

    def register_window_provider(self, provider: UiWindowProviderABC) -> None:
        self._registry.register_window_provider(provider)

    def register_object_state_scope_provider(
        self,
        provider: UiObjectStateScopeProviderABC,
    ) -> None:
        self._registry.register_object_state_scope_provider(provider)

    def _submit_mutation(
        self,
        *,
        operation_type: type[UiBridgeOperation],
        target_id: str | None,
        request: object,
        callback: Callable[[UiBridgeOperationRef], AgentResultEnvelope],
    ) -> AgentResultEnvelope:
        operation = self._mutation_gate.begin(
            operation_type=operation_type,
            target_id=target_id,
        )
        submitted = UiBridgePostedMutation()

        def run() -> None:
            try:
                result = callback(operation)
                self._mutation_gate.complete(operation, operation_type, result)
                submitted.complete(result)
            except Exception as exc:
                self._mutation_gate.fail(operation, exc)
                submitted.fail(exc)

        try:
            self._dispatcher.post(run)
        except Exception as exc:
            self._mutation_gate.fail(operation, exc)
            raise

        if submitted.completed:
            return submitted.require_result()
        return operation_type.accepted(request, operation)

    @serves(UiBridgeStatusOperation)
    def status(self) -> UiBridgeStatus:
        return UiBridgeStatus(
            schema_version=SCHEMA_VERSION,
            reachable=True,
            auth_required=False,
        )

    @serves(UiBridgeListDocumentsOperation)
    def list_documents(self) -> UiCodeDocumentCatalog:
        return self._dispatcher.call(
            lambda: UiCodeDocumentCatalog(
                schema_version=SCHEMA_VERSION,
                documents=tuple(
                    summary
                    for provider in self._registry.code_document_providers()
                    for summary in provider.summaries()
                ),
            )
        )

    @serves(UiBridgeListStateSurfacesOperation)
    def list_state_surfaces(self) -> UiStateSurfaceCatalog:
        return self._dispatcher.call(
            lambda: UiStateSurfaceCatalog(
                schema_version=SCHEMA_VERSION,
                surfaces=tuple(
                    provider.summary() for provider in self._registry.state_surface_providers()
                ),
            )
        )

    @serves(UiBridgeListActionsOperation)
    def list_actions(self) -> UiActionCatalog:
        def catalog() -> UiActionCatalog:
            actions = []
            errors = []
            warnings = []
            for provider in self._registry.action_providers():
                provider_catalog = provider.catalog()
                actions.extend(provider_catalog.actions)
                errors.extend(provider_catalog.errors)
                warnings.extend(provider_catalog.warnings)
            return UiActionCatalog(
                schema_version=SCHEMA_VERSION,
                actions=tuple(actions),
                errors=tuple(errors),
                warnings=tuple(warnings),
            )

        return self._dispatcher.call(catalog)

    @serves(UiBridgeListWindowsOperation)
    def list_windows(self) -> UiWindowCatalog:
        def catalog() -> UiWindowCatalog:
            windows = []
            errors = []
            warnings = []
            for provider in self._registry.window_providers():
                provider_catalog = provider.catalog()
                windows.extend(provider_catalog.windows)
                errors.extend(provider_catalog.errors)
                warnings.extend(provider_catalog.warnings)
            return UiWindowCatalog(
                schema_version=SCHEMA_VERSION,
                windows=tuple(windows),
                errors=tuple(errors),
                warnings=tuple(warnings),
            )

        return self._dispatcher.call(catalog)

    @serves(UiBridgeListObjectStateScopesOperation)
    def list_object_state_scopes(
        self,
        request: UiObjectStateScopeListRequest,
    ) -> UiObjectStateScopeCatalog:
        def catalog() -> UiObjectStateScopeCatalog:
            scopes = []
            errors = []
            warnings = []
            for provider in self._registry.object_state_scope_providers():
                provider_catalog = provider.catalog(request)
                scopes.extend(provider_catalog.scopes)
                errors.extend(provider_catalog.errors)
                warnings.extend(provider_catalog.warnings)
            return UiObjectStateScopeCatalog(
                schema_version=SCHEMA_VERSION,
                object_state_token=ObjectStateRegistry.get_token(),
                current_branch=ObjectStateRegistry.get_current_branch(),
                current_snapshot_index=self._snapshot_provider.current_snapshot_index(),
                active=ObjectStateRegistry.is_time_traveling(),
                scopes=tuple(scopes),
                errors=tuple(errors),
                warnings=tuple(warnings),
            )

        return self._dispatcher.call(catalog)

    @serves(UiBridgeMutateObjectStateFieldOperation)
    def mutate_object_state_field(
        self,
        request: UiObjectStateFieldMutationRequest,
    ) -> UiObjectStateFieldMutationResult:
        def run(operation: UiBridgeOperationRef) -> UiObjectStateFieldMutationResult:
            from formbridge.bridge.object_state import ObjectStateFieldMutationService

            result = ObjectStateFieldMutationService(
                before_mutation=self._object_state_mutation_authorizer,
            ).mutate(request)
            return replace(
                result,
                receipt=replace(
                    result.receipt,
                    bridge_operation_id=operation.identity.operation_id,
                ),
            )

        try:
            return self._dispatcher.call(
                lambda: self._mutation_gate.run(
                    operation_type=UiBridgeMutateObjectStateFieldOperation,
                    target_id=(f"{request.object_state_scope_id}:{request.field_path}"),
                    callback=run,
                )
            )
        except UiBridgeBusyError as exc:
            return UiObjectStateFieldMutationResult(
                schema_version=SCHEMA_VERSION,
                address=request.as_address(),
                mutated=False,
                reset=request.reset,
                receipt=UiMutationReceipt.rejected_for(request.request_token),
                errors=(AgentError.from_exception("ui_bridge_busy", exc),),
            )

    @serves(UiBridgeGetDocumentOperation)
    def get_document(self, request: UiCodeDocumentRequest) -> UiCodeDocument:
        return self._dispatcher.call(
            lambda: self._registry.code_document_provider(request.document_id).read(request)
        )

    @serves(UiBridgeGetStateSurfaceOperation)
    def get_state_surface(self, request: UiStateSurfaceRequest) -> UiStateSurfaceDocument:
        return self._dispatcher.call(
            lambda: self._registry.state_surface_provider(request.surface_id).read(request)
        )

    @serves(UiBridgeInvokeActionOperation)
    def invoke_action(self, request: UiActionInvokeRequest) -> UiActionInvokeResult:
        def run(operation: UiBridgeOperationRef) -> UiActionInvokeResult:
            result = self._registry.action_provider(request.widget_id).invoke(request)
            return replace(
                result,
                receipt=replace(
                    result.receipt,
                    bridge_operation_id=operation.identity.operation_id,
                ),
            )

        try:
            return self._submit_mutation(
                operation_type=UiBridgeInvokeActionOperation,
                target_id=request.action_id,
                request=request,
                callback=run,
            )
        except UiBridgeBusyError as exc:
            return self._action_error(
                request,
                AgentError.from_exception("ui_bridge_busy", exc),
            )

    @serves(UiBridgeFocusWindowOperation)
    def focus_window(self, request: UiWindowFocusRequest) -> UiWindowFocusResult:
        return self._dispatcher.call(
            lambda: self._registry.window_provider(request.window_id).focus(request)
        )

    @serves(UiBridgeNavigateWindowOperation)
    def navigate_window(
        self,
        request: UiWindowNavigateRequest,
    ) -> UiWindowNavigateResult:
        def navigate() -> UiWindowNavigateResult:
            provider = self._registry.window_provider(request.window_id)
            if not request.has_target:
                return provider.navigate(request)
            operation, result = self._operation_tracker.observe(
                UiBridgeNavigateWindowOperation,
                request.window_id,
                partial(provider.navigate, request),
            )
            # Accepted target dispatch is not terminal execution or exposure.
            return replace(
                result,
                operation_id=operation.identity.operation_id,
                navigated=False,
                target_exposed=None,
            )

        return self._dispatcher.call(navigate)

    @serves(UiBridgeCloseWindowOperation)
    def close_window(self, request: UiWindowCloseRequest) -> UiWindowCloseResult:
        return self._dispatcher.call(
            lambda: self._registry.window_provider(request.window_id).close(request)
        )

    @serves(UiBridgeSnapshotWindowOperation)
    def snapshot_window(
        self,
        request: UiWindowSnapshotRequest,
    ) -> UiWindowSnapshotResult:
        def capture() -> UiWindowSnapshotResult:
            provider = self._registry.window_provider(request.window_id)
            if not request.frame_condition.observes:
                return provider.snapshot(request)
            operation, result = self._operation_tracker.observe(
                UiBridgeSnapshotWindowOperation,
                request.window_id,
                partial(provider.snapshot, request),
            )
            return project_dataclass(
                UiWindowSnapshotResult,
                result,
                operation_id=operation.identity.operation_id,
            )

        return self._dispatcher.call(capture)

    @serves(UiBridgeWidgetTreeOperation)
    def widget_tree(
        self,
        request: UiWidgetTreeRequest,
    ) -> UiWidgetTreeResult:
        return self._dispatcher.call(
            lambda: self._registry.window_provider(request.window_id).widget_tree(request)
        )

    @serves(UiBridgeInvokeWidgetActionOperation)
    def invoke_widget_action(
        self,
        request: UiWidgetActionInvokeRequest,
    ) -> UiWidgetActionInvokeResult:
        def run(operation: UiBridgeOperationRef) -> UiWidgetActionInvokeResult:
            provider = self._registry.window_provider(request.window_id)
            result = provider.invoke_widget_action(request)
            return replace(
                result,
                receipt=replace(
                    result.receipt,
                    bridge_operation_id=operation.identity.operation_id,
                ),
            )

        try:
            return self._submit_mutation(
                operation_type=UiBridgeInvokeWidgetActionOperation,
                target_id=f"{request.window_id}:{request.path_id}",
                request=request,
                callback=run,
            )
        except UiBridgeBusyError as exc:
            return self._widget_action_error(
                request,
                AgentError.from_exception("ui_bridge_busy", exc),
            )

    @serves(UiBridgeValidateDocumentOperation)
    def validate_document(
        self,
        request: UiCodeDocumentValidationRequest,
    ) -> UiCodeDocumentValidationResult:
        return self._dispatcher.call(
            lambda: self._registry.code_document_provider(request.document_id).validate(request)
        )

    @serves(UiBridgeApplyDocumentOperation)
    def apply_document(
        self,
        request: UiCodeDocumentApplyRequest,
    ) -> UiCodeDocumentApplyResult:
        def run(operation: UiBridgeOperationRef) -> UiCodeDocumentApplyResult:
            result = self._registry.code_document_provider(request.document_id).apply(request)
            return replace(
                result,
                operation_id=operation.identity.operation_id,
                receipt=replace(
                    result.receipt,
                    bridge_operation_id=operation.identity.operation_id,
                ),
            )

        try:
            return self._submit_mutation(
                operation_type=UiBridgeApplyDocumentOperation,
                target_id=request.document_id,
                request=request,
                callback=run,
            )
        except UiBridgeBusyError as exc:
            return self._apply_document_error(
                request,
                AgentError.from_exception("ui_bridge_busy", exc),
            )

    @serves(UiBridgeListSnapshotsOperation)
    def list_snapshots(self, request: UiSnapshotListRequest) -> UiSnapshotCatalog:
        return self._dispatcher.call(lambda: self._snapshot_provider.list_snapshots(request))

    @serves(UiBridgeRestoreSnapshotOperation)
    def restore_snapshot(
        self,
        request: UiSnapshotRestoreRequest,
    ) -> UiSnapshotRestoreResult:
        def run(operation: UiBridgeOperationRef) -> UiSnapshotRestoreResult:
            result = self._snapshot_provider.restore_snapshot(request)
            return replace(
                result,
                operation_id=operation.identity.operation_id,
                receipt=UiMutationReceipt.accepted_for(
                    UiMutationRequestToken(),
                    bridge_operation_id=operation.identity.operation_id,
                ),
            )

        return self._submit_mutation(
            operation_type=UiBridgeRestoreSnapshotOperation,
            target_id=request.operation_target_id,
            request=request,
            callback=run,
        )

    @serves(UiBridgeTimeTravelHeadOperation)
    def time_travel_head(
        self,
        request: UiTimeTravelHeadRequest,
    ) -> UiSnapshotRestoreResult:
        def run(operation: UiBridgeOperationRef) -> UiSnapshotRestoreResult:
            result = self._snapshot_provider.time_travel_head(request)
            return replace(
                result,
                operation_id=operation.identity.operation_id,
                receipt=UiMutationReceipt.accepted_for(
                    UiMutationRequestToken(),
                    bridge_operation_id=operation.identity.operation_id,
                ),
            )

        return self._submit_mutation(
            operation_type=UiBridgeTimeTravelHeadOperation,
            target_id=None,
            request=request,
            callback=run,
        )

    @serves(UiBridgeListBranchesOperation)
    def list_branches(self) -> UiBranchCatalog:
        return self._dispatcher.call(
            lambda: UiBranchCatalog(
                schema_version=SCHEMA_VERSION,
                current_branch=ObjectStateRegistry.get_current_branch(),
                branches=self._snapshot_provider.branch_refs(),
            )
        )

    @serves(UiBridgeSwitchBranchOperation)
    def switch_branch(self, request: UiBranchSwitchRequest) -> UiSnapshotRestoreResult:
        def run(operation: UiBridgeOperationRef) -> UiSnapshotRestoreResult:
            result = self._snapshot_provider.switch_branch(request)
            return replace(
                result,
                operation_id=operation.identity.operation_id,
                receipt=UiMutationReceipt.accepted_for(
                    UiMutationRequestToken(),
                    bridge_operation_id=operation.identity.operation_id,
                ),
            )

        return self._submit_mutation(
            operation_type=UiBridgeSwitchBranchOperation,
            target_id=request.branch,
            request=request,
            callback=run,
        )

    @serves(UiBridgeGetOperationStatusOperation)
    def get_operation_status(self, request: UiBridgeOperationStatusRequest) -> UiBridgeOperationRef:
        return self._operation_tracker.get(request.operation_id)

    @staticmethod
    def _apply_document_error(
        request: UiCodeDocumentApplyRequest,
        error: AgentError,
    ) -> UiCodeDocumentApplyResult:
        return UiCodeDocumentApplyResult(
            schema_version=SCHEMA_VERSION,
            document_id=request.document_id,
            applied=False,
            base_revision_token=request.base_revision_token,
            receipt=UiMutationReceipt.rejected_for(request.request_token),
            errors=(error,),
        )

    @staticmethod
    def _action_error(
        request: UiActionInvokeRequest,
        error: AgentError,
    ) -> UiActionInvokeResult:
        return UiActionInvokeResult(
            schema_version=SCHEMA_VERSION,
            identity=UiActionIdentity(
                widget_id=request.widget_id,
                action_id=request.action_id,
            ),
            status=ActionRejected,
            receipt=UiMutationReceipt.rejected_for(request.request_token),
            target_scope_ids=request.selected_scope_ids,
            selection_revision_token=request.observed_selection_revision_token,
            errors=(error,),
        )

    @staticmethod
    def _widget_action_error(
        request: UiWidgetActionInvokeRequest,
        error: AgentError,
    ) -> UiWidgetActionInvokeResult:
        return UiWidgetActionInvokeResult(
            schema_version=SCHEMA_VERSION,
            window_id=request.window_id,
            path_id=request.path_id,
            action_kind=request.action_kind,
            invoked=False,
            receipt=UiMutationReceipt.rejected_for(request.request_token),
            errors=(error,),
        )


class InProcessUiBridgeGateway(UiBridgeGatewayABC):
    """Gateway adapter for tests or same-process MCP embedding."""

    def __init__(self, bridge: UiAgentBridgeService) -> None:
        self._bridge = bridge

    def invoke(self, connection: UiBridgeConnectionSpec, operation, request):
        del connection
        return self._bridge.invoke(operation, request)
