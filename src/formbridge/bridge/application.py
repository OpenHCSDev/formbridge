"""The application a running-UI bridge serves.

Every name the bridge writes on the wire, in the environment or on disk comes
from one subclass that the application declares. A process serves one
application, so the generic bridge asks :meth:`UiBridgeApplication.current`.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from pathlib import Path
from typing import ClassVar

from metaclass_registry import AutoRegisterMeta
from zmqruntime import EndpointApplication
from zmqruntime.execution.config import ExecutionTransportConfig


class UiBridgeApplication(ABC, metaclass=AutoRegisterMeta):
    """Declaration of one application's running-UI bridge."""

    __registry_key__ = "protocol_version"
    __skip_if_no_key__ = True

    protocol_version: ClassVar[str | None] = None
    """Bridge protocol spoken by this application's client and server."""

    endpoint_application: ClassVar[EndpointApplication]
    """Application identity answered at endpoint boundaries."""

    transport_config: ClassVar[ExecutionTransportConfig]
    """ZMQ transport configuration for bridge sockets."""

    runtime_name: ClassVar[str]
    """Directory name under the platform runtime root that holds descriptors."""

    descriptor_file_variable: ClassVar[str]
    """Environment variable naming one descriptor file."""

    descriptor_directory_variable: ClassVar[str]
    """Environment variable naming the descriptor directory."""

    server_name: ClassVar[str]
    """Name the bridge server announces to endpoint browsers."""

    service_name: ClassVar[str]
    """Service name reported by the bridge status operation."""

    @classmethod
    @abstractmethod
    def window_snapshot_dir(cls) -> Path:
        """Default directory for window snapshots requested without one."""

    @classmethod
    @abstractmethod
    def log_file_path(cls) -> str | None:
        """The running application's log file, reported by the bridge server."""

    @classmethod
    @abstractmethod
    def connection_environment(cls):
        """Empty ``UiBridgeConnectionFields`` whose fields name their environment variables.

        A client overlays it from the environment onto the connection it was given.
        """

    @classmethod
    @abstractmethod
    def output_path_policy(cls):
        """The ``UiBridgeOutputPathPolicy`` clients apply to files they ask the UI to write."""

    @classmethod
    def descriptor_environment_keys(cls) -> tuple[str, str]:
        """Every selector a descriptor-consuming child process needs."""

        return (cls.descriptor_file_variable, cls.descriptor_directory_variable)

    @staticmethod
    def current() -> type[UiBridgeApplication]:
        """The one application declared in this process."""

        applications = tuple(UiBridgeApplication.__registry__.values())
        if len(applications) != 1:
            raise LookupError(
                "A UI bridge process declares exactly one UiBridgeApplication; "
                f"found {[application.__name__ for application in applications]}."
            )
        return applications[0]
