"""
Core Log Utilities for pyqt-reactor.

Unified log discovery, classification, and monitoring utilities
shared between UI implementations.
"""

import logging
import time
from collections.abc import Callable
from dataclasses import dataclass
from enum import Enum, nonmember
from pathlib import Path
from typing import List, Optional

from zmqruntime.execution.logs import ExecutionWorkerLogIdentity
from zmqruntime.messages import ProcessIdentity

logger = logging.getLogger(__name__)


LogDisplayNameResolver = Callable[[Path, str | None], str]


class LogType(str, Enum):
    """Closed log roles with member-owned presentation and ordering semantics."""

    _path_name = nonmember(lambda path, worker_id: path.name)
    _main_process = nonmember(lambda path, worker_id: "Main Process")
    _main_subprocess = nonmember(lambda path, worker_id: "Main Subprocess")
    _worker = nonmember(
        lambda path, worker_id: (
            f"Worker {worker_id}" if worker_id is not None else path.name
        )
    )

    def __new__(
        cls,
        value: str,
        display_name_resolver: LogDisplayNameResolver,
        sort_priority: int,
        retained_on_clear: bool = False,
    ) -> "LogType":
        member = str.__new__(cls, value)
        member._value_ = value
        member._display_name_resolver = display_name_resolver
        member.sort_priority = sort_priority
        member.retained_on_clear = retained_on_clear
        return member

    TUI = ("tui", _main_process, 0, True)
    MAIN = ("main", _main_subprocess, 1)
    WORKER = ("worker", _worker, 2)
    ZMQ_SERVER = ("zmq_server", _path_name, 3)
    ZMQ_WORKER = ("zmq_worker", _path_name, 3)
    NAPARI = ("napari", _path_name, 3)
    UNKNOWN = ("unknown", _path_name, 3)

    def display_name_for(self, path: Path, worker_id: str | None) -> str:
        """Resolve this member's default display name."""

        return self._display_name_resolver(path, worker_id)


def _get_log_dir() -> Path:
    """Return configured log directory or default."""
    from formbridge.protocols.form_config import get_form_config

    config = get_form_config()
    if config.log_dir:
        return Path(config.log_dir)
    return Path.home() / ".local" / "share" / "formbridge" / "logs"


def _get_log_prefixes() -> List[str]:
    """Return configured log prefixes or default."""
    from formbridge.protocols.form_config import get_form_config

    config = get_form_config()
    return config.log_prefixes or ["formbridge_"]


def _match_prefixed(file_name: str, suffix: str) -> Optional[str]:
    """Return matching prefix for a file name if it starts with prefix+suffix."""
    for prefix in _get_log_prefixes():
        if file_name.startswith(f"{prefix}{suffix}"):
            return prefix
    return None


def get_current_log_file_path() -> str:
    """Get the current log file path from the logging system."""
    from formbridge.protocols.form_config import get_form_config

    try:
        # Get the root logger and find the FileHandler
        root_logger = logging.getLogger()
        for handler in root_logger.handlers:
            if isinstance(handler, logging.FileHandler):
                return handler.baseFilename

        # Fallback: try to get from configured logger name
        config = get_form_config()
        if config.log_root_logger_name:
            root_named_logger = logging.getLogger(config.log_root_logger_name)
            for handler in root_named_logger.handlers:
                if isinstance(handler, logging.FileHandler):
                    return handler.baseFilename

        # Last resort: create a default path
        log_dir = _get_log_dir()
        log_dir.mkdir(parents=True, exist_ok=True)
        prefix = (_get_log_prefixes() or ["formbridge_"])[0]
        return str(log_dir / f"{prefix}subprocess_{int(time.time())}.log")

    except Exception as e:
        logger.error(f"Failed to get current log file path: {e}")
        raise RuntimeError(f"Could not determine log file path: {e}")


@dataclass(slots=True)
class LogFileInfo:
    """Information about a discovered log file."""

    path: Path
    log_type: LogType
    worker_id: Optional[str] = None
    display_name: Optional[str] = None
    process_identity: Optional[ProcessIdentity] = None

    def __post_init__(self):
        """Generate display name if not provided."""
        if self.display_name is None:
            self.display_name = self.log_type.display_name_for(
                self.path,
                self.worker_id,
            )


def discover_logs(base_log_path: Optional[str] = None, include_main_log: bool = True,
                 log_directory: Optional[Path] = None) -> List[LogFileInfo]:
    """
    Discover application log files and return as classified LogFileInfo objects.

    Args:
        base_log_path: Base path for specific subprocess logs (optional)
        include_main_log: Whether to include the current main process log
        log_directory: Directory to search (defaults to configured log directory)

    Returns:
        List of LogFileInfo objects for discovered log files
    """
    discovered_logs = []

    # Include current main process log if requested
    if include_main_log:
        try:
            main_log_path = get_current_log_file_path()
            main_log = Path(main_log_path)
            if main_log.exists():
                log_info = classify_log_file(main_log, base_log_path, include_main_log)
                discovered_logs.append(log_info)
        except Exception:
            pass  # Main log not available, continue

    # Discover subprocess logs if base_log_path is provided
    if base_log_path:
        base_path = Path(base_log_path)
        log_dir = base_path.parent
        if log_dir.exists():
            for log_file in log_dir.glob("*.log"):
                if is_relevant_log_file(log_file, base_log_path):
                    log_info = classify_log_file(log_file, base_log_path, include_main_log)
                    discovered_logs.append(log_info)

    # Discover all logs if no specific base_log_path
    elif log_directory or not base_log_path:
        if log_directory is None:
            log_directory = _get_log_dir()

        if log_directory.exists():
            for log_file in log_directory.glob("*.log"):
                if is_app_log_file(log_file) and log_file not in [log.path for log in discovered_logs]:
                    # Infer base_log_path for proper classification
                    inferred_base = infer_base_log_path(log_file) if 'subprocess_' in log_file.name else None
                    log_info = classify_log_file(log_file, inferred_base, include_main_log)
                    discovered_logs.append(log_info)

    return discovered_logs


def classify_log_file(log_path: Path, base_log_path: Optional[str] = None, include_tui_log: bool = True) -> LogFileInfo:
    """
    Pure function: Classify a log file and extract metadata.

    Args:
        log_path: Path to log file
        base_log_path: Base path for subprocess log files
        include_tui_log: Whether to check for TUI log classification

    Returns:
        LogFileInfo with classification and metadata
    """
    file_name = log_path.name

    # Check if it's the current TUI log
    if include_tui_log:
        try:
            tui_log_path = get_current_log_file_path()
            if log_path == Path(tui_log_path):
                return LogFileInfo(
                    log_path,
                    LogType.TUI,
                    process_identity=ProcessIdentity.current(),
                )
        except RuntimeError:
            pass  # TUI log not found, continue with other classification

    # Check for ZMQ server logs (<prefix>zmq_server_port_{port}_{timestamp}.log)
    prefix = _match_prefixed(file_name, "zmq_server_port_")
    if prefix:
        # Extract port from filename
        parts = file_name.replace(f'{prefix}zmq_server_port_', '').replace('.log', '').split('_')
        port = parts[0] if parts else 'unknown'
        return LogFileInfo(
            log_path,
            LogType.ZMQ_SERVER,
            display_name=f"ZMQ Server (port {port})",
        )

    # Check for ZMQ worker logs
    worker_log = ExecutionWorkerLogIdentity.from_path(log_path)
    if worker_log is not None:
        worker_id = str(worker_log.worker_pid)
        return LogFileInfo(
            log_path,
            LogType.ZMQ_WORKER,
            worker_id,
            display_name=f"ZMQ Worker {worker_id}",
        )

    # Check for Napari viewer logs
    if file_name.startswith('napari_detached_port_'):
        port = file_name.replace('napari_detached_port_', '').replace('.log', '')
        return LogFileInfo(
            log_path,
            LogType.NAPARI,
            display_name=f"Napari Viewer (port {port})",
        )

    # Check subprocess logs if base_log_path is provided
    if base_log_path:
        base_name = Path(base_log_path).name

        # Check if it's the main subprocess log: exact match
        if file_name == f"{base_name}.log":
            return LogFileInfo(log_path, LogType.MAIN)

        # Check if it's a worker log: {base_name}_worker_*.log
        if file_name.startswith(f"{base_name}_worker_") and file_name.endswith('.log'):
            # Extract worker ID (everything between _worker_ and .log)
            worker_part = file_name[len(f"{base_name}_worker_"):-4]  # Remove .log suffix
            worker_id = worker_part.split('_')[0]  # Take first part before any additional underscores
            return LogFileInfo(log_path, LogType.WORKER, worker_id)

    # Unknown or malformed log file
    logger.debug(f"Unrecognized log file pattern: {file_name}")
    return LogFileInfo(log_path, LogType.UNKNOWN)


def is_relevant_log_file(file_path: Path, base_log_path: Optional[str]) -> bool:
    """
    Check if file is a relevant log file for monitoring.

    Args:
        file_path: Path to file to check
        base_log_path: Base path for subprocess log files

    Returns:
        bool: True if file is relevant for monitoring
    """
    if not base_log_path:
        return False

    base_name = Path(base_log_path).name
    file_name = file_path.name

    # Check if it matches our patterns
    if file_name == f"{base_name}.log":
        return True

    if file_name.startswith(f"{base_name}_worker_") and file_name.endswith('.log'):
        return True

    return False


def is_app_log_file(file_path: Path) -> bool:
    """
    Check if a file is a recognized application log file.

    Args:
        file_path: Path to file to check

    Returns:
        bool: True if file matches configured log prefixes
    """
    if not file_path.name.endswith('.log'):
        return False

    file_name = file_path.name

    # App log patterns based on configured prefixes, plus common auxiliary logs
    prefixes = _get_log_prefixes()
    extra_patterns = [
        "pyqt_gui_subprocess_",
        "zmq_worker_",
        "napari_detached_",
    ]
    patterns = [*prefixes, *extra_patterns]

    return any(file_name.startswith(pattern) for pattern in patterns)


def infer_base_log_path(file_path: Path) -> str:
    """
    Infer the base log path from a subprocess log file name.

    Args:
        file_path: Path to subprocess log file

    Returns:
        str: Inferred base log path
    """
    file_name = file_path.name

    # Handle worker logs: remove _worker_* suffix
    if '_worker_' in file_name:
        base_name = file_name.split('_worker_')[0]
    else:
        # Handle main subprocess logs: remove .log extension
        base_name = file_path.stem

    return str(file_path.parent / base_name)


# Backward compatibility alias
is_openhcs_log_file = is_app_log_file
