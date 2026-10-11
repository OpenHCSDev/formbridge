"""ZMQ transport for the running-UI bridge."""

from __future__ import annotations

import uuid
from collections.abc import Mapping

from python_introspect import JsonObject, dataclass_from_mapping, to_jsonable

from formbridge.bridge.application import UiBridgeApplication
from formbridge.bridge.dto import (
    UiBridgeConnectionSpec,
    UiBridgeRequestEnvelope,
    UiBridgeResponseEnvelope,
)
from formbridge.bridge.service import (
    DEFAULT_UI_BRIDGE_TIMEOUT_MS,
    UiBridgeGatewayABC,
    UiBridgeGatewayResponseError,
    UiBridgeGatewayTimeoutError,
    UiBridgeGatewayUnavailableError,
    UiBridgeOperation,
)
from formbridge.contracts import SCHEMA_VERSION

UI_BRIDGE_CONTROL_TIMEOUT_MAX_MS = DEFAULT_UI_BRIDGE_TIMEOUT_MS
UI_BRIDGE_CONTROL_TIMEOUT_MIN_MS = 1


class UiBridgeControlClient:
    """Small JSON/ZMQ client for the UI bridge control socket."""

    def request(
        self,
        connection: UiBridgeConnectionSpec,
        operation: type[UiBridgeOperation],
        request=None,
    ) -> JsonObject:
        if connection.port is None:
            raise UiBridgeGatewayUnavailableError
        operation.validate_request(request)

        request = UiBridgeRequestEnvelope(
            schema_version=SCHEMA_VERSION,
            bridge_protocol_version=UiBridgeApplication.current().protocol_version,
            application=UiBridgeApplication.current().endpoint_application,
            request_id=str(uuid.uuid4()),
            operation=operation.require_name(),
            auth_token=connection.auth_token,
            payload=self._payload_object(request),
        )
        response_payload = self._send(connection, to_jsonable(request))
        response = dataclass_from_mapping(
            UiBridgeResponseEnvelope,
            response_payload,
        )
        self._validate_response(request, response)
        if not response.ok:
            raise UiBridgeGatewayResponseError(response.errors)
        return response.payload

    def _send(
        self,
        connection: UiBridgeConnectionSpec,
        request_payload: JsonObject,
    ) -> JsonObject:
        import zmq

        context = zmq.Context.instance()
        socket = context.socket(zmq.REQ)
        timeout_ms = self._socket_timeout_ms(connection)
        request_operation = self._request_operation(request_payload)
        socket.setsockopt(zmq.LINGER, 0)
        socket.setsockopt(zmq.RCVTIMEO, timeout_ms)
        socket.setsockopt(zmq.SNDTIMEO, timeout_ms)
        try:
            socket.connect(connection.zmq_data_url(UiBridgeApplication.current().transport_config))
            socket.send_json(request_payload)
            response = socket.recv_json()
        except zmq.Again as exc:
            raise UiBridgeGatewayTimeoutError(
                operation=request_operation,
                timeout_ms=timeout_ms,
            ) from exc
        finally:
            socket.close(linger=0)
        if not isinstance(response, Mapping):
            raise TypeError(
                f"UI bridge response must be a JSON object, got {type(response).__name__}"
            )
        return dict(response)

    @staticmethod
    def _socket_timeout_ms(connection: UiBridgeConnectionSpec) -> int:
        return min(
            max(connection.timeout_ms, UI_BRIDGE_CONTROL_TIMEOUT_MIN_MS),
            UI_BRIDGE_CONTROL_TIMEOUT_MAX_MS,
        )

    @staticmethod
    def _request_operation(request_payload: JsonObject) -> str:
        if "operation" not in request_payload:
            raise ValueError("UI bridge request payload missing required field 'operation'.")
        operation = request_payload["operation"]
        if not isinstance(operation, str):
            raise TypeError("UI bridge request payload field 'operation' must be a string.")
        return operation

    @staticmethod
    def _payload_object(payload) -> JsonObject:
        if payload is None:
            return {}
        json_payload = to_jsonable(payload)
        if not isinstance(json_payload, Mapping):
            raise TypeError(
                f"UI bridge request payload must serialize to a JSON object, "
                f"got {type(json_payload).__name__}"
            )
        return json_payload

    @staticmethod
    def _validate_response(
        request: UiBridgeRequestEnvelope,
        response: UiBridgeResponseEnvelope,
    ) -> None:
        if response.schema_version != SCHEMA_VERSION:
            raise ValueError(f"Unsupported agent schema version: {response.schema_version}")
        application = UiBridgeApplication.current()
        if response.bridge_protocol_version != application.protocol_version:
            raise ValueError(
                f"Unsupported UI bridge protocol version: {response.bridge_protocol_version}"
            )
        application.endpoint_application.compatibility_with(response.application).require_match()
        if response.request_id != request.request_id:
            raise ValueError("UI bridge response request_id does not match request.")


class ZMQUiBridgeGateway(UiBridgeGatewayABC):
    """Gateway that connects agent services to a running UI bridge."""

    def __init__(self, client: UiBridgeControlClient | None = None) -> None:
        if client is None:
            client = UiBridgeControlClient()
        self._client = client

    def invoke(
        self,
        connection: UiBridgeConnectionSpec,
        operation: type[UiBridgeOperation],
        request,
    ):
        return dataclass_from_mapping(
            operation.result_type,
            self._client.request(connection, operation, request),
        )
