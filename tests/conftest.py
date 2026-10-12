"""One bridge application for the test process, as an application declares it."""

from __future__ import annotations

from pathlib import Path

from zmqruntime import EndpointApplication
from zmqruntime.execution.config import ExecutionTransportConfig

from formbridge.bridge.application import UiBridgeApplication
from formbridge.bridge.dto import UiBridgeConnectionFields
from formbridge.bridge.service import UiBridgeOutputPathPolicy, UiBridgeRequestRejectedError
from formbridge.contracts import AgentError


class _AnyDirectory(UiBridgeOutputPathPolicy):
    def writable_directory(self, path: str | Path) -> Path:
        candidate = Path(path)
        if not candidate.is_absolute():
            raise UiBridgeRequestRejectedError((AgentError("relative_path", str(path)),))
        return candidate


class ExampleBridgeApplication(UiBridgeApplication):
    protocol_version = "example.ui_bridge.v1"
    endpoint_application = EndpointApplication(identifier="example", version="1.0")
    transport_config = ExecutionTransportConfig(
        ipc_socket_prefix="formbridge-test", app_name="formbridge-test"
    )
    runtime_name = "FormbridgeTest"
    descriptor_file_variable = "FORMBRIDGE_TEST_BRIDGE_DESCRIPTOR"
    descriptor_directory_variable = "FORMBRIDGE_TEST_BRIDGE_DESCRIPTOR_DIR"
    server_name = "ExampleBridgeServer"
    service_name = "example.ui_bridge"

    @classmethod
    def window_snapshot_dir(cls) -> Path:
        return Path("/tmp/example-snapshots")

    @classmethod
    def log_file_path(cls) -> str | None:
        return None

    @classmethod
    def connection_environment(cls):
        return UiBridgeConnectionFields()

    @classmethod
    def output_path_policy(cls):
        return _AnyDirectory()
