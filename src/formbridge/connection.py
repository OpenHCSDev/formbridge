"""Typed ZMQ endpoint connection shared by servers and their lightweight clients."""

from __future__ import annotations

from dataclasses import asdict, dataclass, field, replace

from python_introspect import (
    JsonObject,
    project_dataclass,
    validate_annotated_dataclass,
)
from zmqruntime.config import NonBlankString, SocketPort, TransportMode
from zmqruntime.execution.config import ExecutionTransportConfig
from zmqruntime.transport import TransportEndpoint

from formbridge.contracts import AgentDataclassCliRequest


@dataclass(frozen=True, slots=True)
class EndpointConnectionSpec(AgentDataclassCliRequest):
    host: NonBlankString = "localhost"
    """Host of the endpoint in TCP mode; IPC endpoints are local."""
    port: SocketPort | None = None
    """Data port of the endpoint."""
    transport_mode: TransportMode | None = None
    """TCP or IPC; ``None`` uses the transport's platform preference."""
    persistent: bool = True
    """Advertise connections as reusable across successive client requests."""

    def __post_init__(self) -> None:
        validate_annotated_dataclass(self)

    def require_port(self, purpose: str) -> int:
        if self.port is None:
            raise ValueError(f"{purpose} requires an explicit port.")
        return self.port

    def transport_mode_value(self) -> str | None:
        return TransportMode.optional_to_text(self.transport_mode)

    def runtime_arguments(self) -> dict[str, object]:
        """Project exact typed constructor arguments for this connection."""

        return asdict(self.public_connection())

    def specified_runtime_arguments(self) -> dict[str, object]:
        """Project typed constructor arguments while omitting unset optionals."""

        return {
            name: value for name, value in self.runtime_arguments().items() if value is not None
        }

    def tool_arguments(self) -> JsonObject:
        """Project the canonical JSON-compatible tool argument fields."""

        arguments = self.runtime_arguments()
        arguments["transport_mode"] = self.transport_mode_value()
        return arguments

    def public_connection(self) -> EndpointConnectionSpec:
        """Return the credential-free base connection declaration."""

        return project_dataclass(EndpointConnectionSpec, self)

    def zmq_data_url(self, config: ExecutionTransportConfig) -> str:
        return self.transport_endpoint(config, purpose="ZMQ data URL").data_url(config)

    def zmq_control_port(self, config: ExecutionTransportConfig) -> int:
        return self.transport_endpoint(config, purpose="ZMQ control port").control_port(config)

    def zmq_control_url(self, config: ExecutionTransportConfig) -> str:
        return self.transport_endpoint(config, purpose="ZMQ control URL").control_url(config)

    def transport_endpoint(
        self,
        config: ExecutionTransportConfig,
        *,
        purpose: str = "ZMQ transport endpoint",
    ) -> TransportEndpoint:
        """Project the exact route using the supplied transport config."""

        return config.client_endpoint(
            self.require_port(purpose),
            host=self.host,
            transport_mode=self.transport_mode,
        )

    def resolved(self, config: ExecutionTransportConfig) -> EndpointConnectionSpec:
        """Retain effective routing in the public nominal connection."""

        return replace(
            self.public_connection(),
            transport_mode=self.transport_endpoint(config).transport_mode,
        )


@dataclass(frozen=True, kw_only=True)
class EndpointConnectionFields:
    """A request or result that carries one endpoint connection."""

    connection: EndpointConnectionSpec = field(default_factory=EndpointConnectionSpec)

    @property
    def host(self) -> str:
        return self.connection.host

    @property
    def port(self) -> int | None:
        return self.connection.port

    @property
    def transport_mode(self) -> TransportMode | None:
        return self.connection.transport_mode
