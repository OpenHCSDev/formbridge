"""Nominal host contracts for log discovery and server scanning."""

from abc import ABC, abstractmethod
from pathlib import Path

from formbridge.core.log_utils import LogFileInfo


class LogDiscoveryProviderABC(ABC):
    """Host-owned source of application log files."""

    @abstractmethod
    def get_current_log_path(self) -> Path:
        """Return current log file path."""
        raise NotImplementedError

    @abstractmethod
    def discover_logs(
        self,
        base_log_path: str | None = None,
        include_main_log: bool = True,
        log_directory: Path | None = None,
    ) -> list[LogFileInfo]:
        """Return discovered logs."""
        raise NotImplementedError


class ServerScanProviderABC(ABC):
    """Host-owned source of logs advertised by live servers."""

    @abstractmethod
    def scan_for_server_logs(self) -> list[LogFileInfo]:
        """Return logs discovered from live servers."""
        raise NotImplementedError


_log_discovery_provider: LogDiscoveryProviderABC | None = None
_server_scan_provider: ServerScanProviderABC | None = None


def register_log_discovery_provider(provider: LogDiscoveryProviderABC) -> None:
    """Register a global log discovery provider."""
    if not isinstance(provider, LogDiscoveryProviderABC):
        raise TypeError("Log discovery providers must inherit LogDiscoveryProviderABC.")
    global _log_discovery_provider
    _log_discovery_provider = provider


def get_log_discovery_provider() -> LogDiscoveryProviderABC | None:
    """Get the registered log discovery provider."""
    return _log_discovery_provider


def register_server_scan_provider(provider: ServerScanProviderABC) -> None:
    """Register a global server scan provider."""
    if not isinstance(provider, ServerScanProviderABC):
        raise TypeError("Server scan providers must inherit ServerScanProviderABC.")
    global _server_scan_provider
    _server_scan_provider = provider


def get_server_scan_provider() -> ServerScanProviderABC | None:
    """Get the registered server scan provider."""
    return _server_scan_provider
