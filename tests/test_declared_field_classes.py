"""A bridge field declared as one class carries that class, not a subclass of it."""

from __future__ import annotations

import pytest
from python_introspect import dataclass_from_mapping, to_jsonable

from formbridge.bridge.dto import (
    UiActionInvokeRequest,
    UiActionSummary,
    UiBridgeConnectionSpec,
    UiBridgeEndpointIdentity,
    UiCodeDocumentRequest,
    UiCodeDocumentSummary,
    UiMutationReceipt,
    UiObjectStateFieldMutationRequest,
    UiObjectStateFieldMutationResult,
    UiSemanticAddress,
    UiStateSurfaceRequest,
    UiStateSurfaceSummary,
    UiWidgetTreeRequest,
    UiWindowSummary,
)
from formbridge.bridge.service import UiBridgeMutateObjectStateFieldOperation
from formbridge.contracts import SCHEMA_VERSION

_MUTATION = UiObjectStateFieldMutationRequest.from_fields(
    object_state_scope_id="scope", field_path="field", value=1
)


@pytest.mark.parametrize(
    "carrier",
    (
        UiObjectStateFieldMutationResult(
            schema_version=SCHEMA_VERSION,
            address=_MUTATION,
            mutated=False,
            reset=False,
            receipt=UiMutationReceipt.rejected_for(_MUTATION.request_token),
        ),
        UiBridgeEndpointIdentity(connection=UiBridgeConnectionSpec(port=1, auth_token="token")),
        UiCodeDocumentSummary(
            widget_id="widget",
            schema_version=SCHEMA_VERSION,
            identity=UiCodeDocumentRequest(document_id="document"),
            title="title",
            readable=True,
            writable=False,
        ),
        UiStateSurfaceSummary(
            widget_id="widget",
            schema_version=SCHEMA_VERSION,
            identity=UiStateSurfaceRequest.from_fields(surface_id="surface"),
            title="title",
            readable=True,
        ),
        UiActionSummary(
            schema_version=SCHEMA_VERSION,
            identity=UiActionInvokeRequest(widget_id="widget", action_id="action"),
            title="title",
            enabled=True,
            invocation_mode="immediate",
        ),
        UiWindowSummary(
            schema_version=SCHEMA_VERSION,
            identity=UiWidgetTreeRequest(window_id="window", open_policy="existing"),
            title="title",
            window_kind="kind",
            visible=True,
            focusable=True,
        ),
    ),
    ids=lambda carrier: type(carrier).__name__,
)
def test_subclass_in_a_field_declared_as_one_class_is_refused(carrier: object) -> None:
    with pytest.raises(ValueError, match="undeclared field"):
        dataclass_from_mapping(type(carrier), to_jsonable(carrier))


def test_refused_mutation_result_carries_the_address_alone() -> None:
    result = UiBridgeMutateObjectStateFieldOperation.failed(_MUTATION, ())

    assert type(result.address) is UiSemanticAddress
    assert dataclass_from_mapping(type(result), to_jsonable(result)) == result
