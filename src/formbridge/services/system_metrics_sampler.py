"""Cached system metrics sampling for monitor widgets."""

from __future__ import annotations

import platform
import shutil
import subprocess
import threading
from abc import ABC, abstractmethod
from collections.abc import Callable
from dataclasses import dataclass
from enum import Enum
from typing import ClassVar, Generic, TypeVar

from metaclass_registry import AutoRegisterMeta
import psutil
from python_introspect import validate_annotated_dataclass
from zmqruntime.config import PositiveFloat
from zmqruntime.process_launch import BackgroundProcessLaunchPolicy

try:
    import GPUtil
    GPU_AVAILABLE = True
except ImportError:  # pragma: no cover - depends on optional runtime package
    GPUtil = None
    GPU_AVAILABLE = False


def is_wsl() -> bool:
    """Check if running in Windows Subsystem for Linux."""
    return "microsoft" in platform.uname().release.lower()


def get_cpu_freq_mhz() -> int:
    """Get CPU frequency in MHz, with WSL compatibility."""
    if is_wsl():
        try:
            output = subprocess.check_output(
                [
                    "powershell.exe",
                    "-Command",
                    "Get-CimInstance -ClassName Win32_Processor | Select-Object -ExpandProperty CurrentClockSpeed",
                ],
                stderr=subprocess.DEVNULL,
                timeout=2,
                **BackgroundProcessLaunchPolicy.current().popen_arguments(),
            )
            return int(output.strip())
        except Exception:
            return 0
    try:
        freq = psutil.cpu_freq()
        return int(freq.current) if freq else 0
    except Exception:
        return 0


MetricT = TypeVar("MetricT")


@dataclass(frozen=True, slots=True)
class PollingCadence:
    """Validated cadence shared by every background metric poller."""

    seconds: PositiveFloat

    def __post_init__(self) -> None:
        validate_annotated_dataclass(self)

    @property
    def loop_milliseconds(self) -> int:
        """Return the cadence for command-line pollers in milliseconds."""

        return max(100, int(self.seconds * 1000))


class GpuTemperatureSampling(Enum):
    """Closed GPU-temperature sampling policy with member-owned projection."""

    def __new__(
        cls,
        enabled: bool,
        projector: Callable[[float], float],
    ) -> "GpuTemperatureSampling":
        member = object.__new__(cls)
        member._value_ = enabled
        member._projector = projector
        return member

    ENABLED = (True, lambda temperature: temperature)
    DISABLED = (False, lambda _temperature: 0.0)

    def project(self, temperature: float) -> float:
        """Apply this member's temperature leaf."""

        return self._projector(temperature)


class BackgroundPollerABC(ABC, metaclass=AutoRegisterMeta):
    """Template owning shared cadence and thread lifecycle for metric pollers."""

    __registry_key__ = "registry_key"
    __skip_if_no_key__ = True
    registry_key: ClassVar[str | None] = None

    def __init__(self, *, cadence: PollingCadence, thread_name: str) -> None:
        self.cadence = cadence
        self._thread_name = thread_name
        self._lock = threading.Lock()
        self._thread: threading.Thread | None = None
        self._closed = False
        self._start_attempted = False

    def start(self) -> None:
        """Start this poller at most once through its concrete preparation hook."""

        if self._closed or self._start_attempted:
            return
        self._start_attempted = True
        if not self._prepare_start():
            return
        self._thread = threading.Thread(
            target=self._run,
            name=self._thread_name,
            daemon=True,
        )
        self._thread.start()

    def stop(self) -> None:
        """Stop concrete resources, then join the shared worker thread."""

        self._closed = True
        self._request_stop()
        if self._thread is not None:
            self._thread.join(timeout=1.0)
            self._thread = None

    @abstractmethod
    def _prepare_start(self) -> bool:
        """Prepare backend resources and report whether the thread should start."""

    @abstractmethod
    def _request_stop(self) -> None:
        """Request that the concrete polling loop stop."""

    @abstractmethod
    def _run(self) -> None:
        """Run the concrete polling loop."""


class BackgroundMetricPoller(BackgroundPollerABC, Generic[MetricT]):
    """Run one blocking metric probe on a background cadence."""

    registry_key = "metric_probe"

    def __init__(
        self,
        *,
        name: str,
        cadence: PollingCadence,
        probe: Callable[[], MetricT],
        default: MetricT,
    ) -> None:
        super().__init__(cadence=cadence, thread_name=name)
        self._probe = probe
        self._value = default
        self._stop_event = threading.Event()

    def latest(self) -> MetricT:
        self.start()
        with self._lock:
            return self._value

    def _prepare_start(self) -> bool:
        return True

    def _request_stop(self) -> None:
        self._stop_event.set()

    def _run(self) -> None:
        while not self._stop_event.is_set():
            try:
                value = self._probe()
            except Exception:
                value = self.latest()
            with self._lock:
                self._value = value
            self._stop_event.wait(self.cadence.seconds)


@dataclass(frozen=True, slots=True)
class SystemMetricsSamplerConfig:
    """Typed policy for expensive system metric providers.

    Args:
        enable_gpu_monitoring: Sample GPU utilization and memory metrics when
            enabled; disabling this avoids GPU provider and process discovery.
        gpu_temperature_monitoring: Include GPU temperature in GPU samples when
            GPU monitoring is enabled.
        cpu_frequency_monitoring: Sample the current CPU frequency through a
            cached background probe.
        gpu_refresh_seconds: Positive interval in seconds between GPU samples.
        cpu_frequency_refresh_seconds: Positive interval in seconds between CPU
            frequency samples.
    """

    enable_gpu_monitoring: bool = True
    gpu_temperature_monitoring: bool = True
    cpu_frequency_monitoring: bool = True
    gpu_refresh_seconds: PositiveFloat = 1.0
    cpu_frequency_refresh_seconds: PositiveFloat = 5.0

    def __post_init__(self) -> None:
        validate_annotated_dataclass(self)

    @property
    def gpu_temperature_sampling(self) -> GpuTemperatureSampling:
        """Return the nominal policy selected by the editable boolean leaf."""

        return GpuTemperatureSampling(self.gpu_temperature_monitoring)


@dataclass(frozen=True, slots=True)
class CpuMetrics:
    """Typed CPU metrics snapshot."""

    cpu_percent: float = 0.0
    cpu_cores: int = 0
    cpu_freq_mhz: int = 0


@dataclass(frozen=True, slots=True)
class MemoryMetrics:
    """Typed system-memory metrics snapshot."""

    ram_percent: float = 0.0
    ram_used_gb: float = 0.0
    ram_total_gb: float = 0.0
    ram_available_gb: float = 0.0

    @classmethod
    def from_psutil(cls, memory) -> "MemoryMetrics":
        """Create one memory snapshot from psutil's virtual-memory result."""

        return cls(
            ram_percent=memory.percent,
            ram_used_gb=memory.used / (1024**3),
            ram_total_gb=memory.total / (1024**3),
            ram_available_gb=memory.available / (1024**3),
        )


@dataclass(frozen=True, slots=True)
class GpuMetrics:
    """Typed GPU metrics snapshot."""

    gpu_percent: float = 0.0
    vram_percent: float = 0.0
    gpu_name: str = "GPU Pending"
    gpu_temp: float = 0.0
    vram_used_mb: float = 0.0
    vram_total_mb: float = 0.0

    @classmethod
    def unavailable(cls, name: str) -> "GpuMetrics":
        return cls(gpu_name=name)


@dataclass(frozen=True, slots=True)
class SystemMetrics:
    """Composite system snapshot that consumes each metric authority directly."""

    cpu: CpuMetrics = CpuMetrics()
    memory: MemoryMetrics = MemoryMetrics()
    gpu: GpuMetrics = GpuMetrics()

    @classmethod
    def from_components(
        cls,
        *,
        cpu_percent: float,
        ram,
        cpu_cores: int,
        cpu_freq_mhz: int,
        gpu: GpuMetrics,
    ) -> "SystemMetrics":
        return cls(
            cpu=CpuMetrics(
                cpu_percent=cpu_percent,
                cpu_cores=cpu_cores,
                cpu_freq_mhz=cpu_freq_mhz,
            ),
            memory=MemoryMetrics.from_psutil(ram),
            gpu=gpu,
        )

    @classmethod
    def error(cls) -> "SystemMetrics":
        return cls(gpu=GpuMetrics.unavailable("Error"))


def _parse_number(value: str) -> float:
    cleaned = value.strip().replace("%", "")
    if cleaned in {"", "N/A", "[N/A]"}:
        return 0.0
    try:
        return float(cleaned)
    except ValueError:
        return 0.0


class PersistentNvidiaSmiPoller(BackgroundPollerABC):
    """Maintain latest NVIDIA GPU metrics from one long-lived nvidia-smi process."""

    registry_key = "nvidia_smi"

    def __init__(
        self,
        *,
        cadence: PollingCadence,
        temperature_sampling: GpuTemperatureSampling,
    ) -> None:
        super().__init__(cadence=cadence, thread_name="NvidiaSmiPoller")
        self.temperature_sampling = temperature_sampling
        self._latest_metrics = GpuMetrics.unavailable("GPU Pending")
        self._process: subprocess.Popen[str] | None = None

    def latest_metrics(self) -> GpuMetrics:
        """Return latest cached GPU metrics, starting the poller if needed."""
        self.start()
        with self._lock:
            return self._latest_metrics

    def _prepare_start(self) -> bool:
        executable = shutil.which("nvidia-smi")
        if executable is None:
            with self._lock:
                self._latest_metrics = GpuMetrics.unavailable("NVIDIA SMI Not Available")
            return False

        command = [
            executable,
            "--id=0",
            "--query-gpu=utilization.gpu,temperature.gpu,memory.used,memory.total,name",
            "--format=csv,noheader,nounits",
            f"--loop-ms={self.cadence.loop_milliseconds}",
        ]
        try:
            self._process = subprocess.Popen(
                command,
                stdout=subprocess.PIPE,
                stderr=subprocess.DEVNULL,
                text=True,
                bufsize=1,
                **BackgroundProcessLaunchPolicy.current().popen_arguments(),
            )
        except Exception:
            self._process = None
            with self._lock:
                self._latest_metrics = GpuMetrics.unavailable("NVIDIA SMI Error")
            return False
        return True

    def _request_stop(self) -> None:
        process = self._process
        self._process = None
        if process is None:
            return
        try:
            process.terminate()
            process.wait(timeout=1.0)
        except Exception:
            try:
                process.kill()
            except Exception:
                pass

    def _run(self) -> None:
        process = self._process
        if process is None or process.stdout is None:
            return

        try:
            for line in process.stdout:
                parsed = self._parse_gpu_line(line)
                if parsed is None:
                    continue
                with self._lock:
                    self._latest_metrics = parsed
        finally:
            with self._lock:
                if self._latest_metrics.gpu_name == "GPU Pending":
                    self._latest_metrics = GpuMetrics.unavailable("NVIDIA SMI Error")

    def _parse_gpu_line(self, line: str) -> GpuMetrics | None:
        parts = [part.strip() for part in line.strip().split(",", 4)]
        if len(parts) != 5:
            return None

        gpu_percent = _parse_number(parts[0])
        gpu_temp = self.temperature_sampling.project(_parse_number(parts[1]))
        vram_used_mb = _parse_number(parts[2])
        vram_total_mb = _parse_number(parts[3])
        gpu_name = parts[4] or "NVIDIA GPU"
        vram_percent = (
            (vram_used_mb / vram_total_mb) * 100.0
            if vram_total_mb > 0
            else 0.0
        )
        return GpuMetrics(
            gpu_percent=gpu_percent,
            vram_percent=vram_percent,
            gpu_name=gpu_name,
            gpu_temp=gpu_temp,
            vram_used_mb=vram_used_mb,
            vram_total_mb=vram_total_mb,
        )


class SystemMetricsSampler:
    """Collect cheap per-tick metrics while caching slow system probes."""

    def __init__(
        self,
        config: SystemMetricsSamplerConfig | None = None,
    ) -> None:
        self.config = config or SystemMetricsSamplerConfig()

        self._cpu_cores = psutil.cpu_count() or 0
        self._cpu_frequency_poller = (
            BackgroundMetricPoller(
                name="CpuFrequencyPoller",
                cadence=PollingCadence(
                    self.config.cpu_frequency_refresh_seconds
                ),
                probe=get_cpu_freq_mhz,
                default=0,
            )
            if self.config.cpu_frequency_monitoring
            else None
        )
        self._gpu_metrics = self._initial_gpu_metrics()
        self._gpu_poller = (
            PersistentNvidiaSmiPoller(
                cadence=PollingCadence(self.config.gpu_refresh_seconds),
                temperature_sampling=self.config.gpu_temperature_sampling,
            )
            if self.config.enable_gpu_monitoring
            else None
        )

    def collect_metrics(self) -> SystemMetrics:
        """Collect a monitor sample, refreshing expensive probes only on schedule."""
        cpu_percent = psutil.cpu_percent(interval=None)
        ram = psutil.virtual_memory()

        return SystemMetrics.from_components(
            cpu_percent=cpu_percent,
            ram=ram,
            cpu_cores=self._cpu_cores,
            cpu_freq_mhz=self._cached_cpu_frequency(),
            gpu=self._cached_gpu_metrics(),
        )

    def _cached_cpu_frequency(self) -> int:
        if self._cpu_frequency_poller is None:
            return 0
        return int(self._cpu_frequency_poller.latest() or 0)

    def _cached_gpu_metrics(self) -> GpuMetrics:
        if not self.config.enable_gpu_monitoring:
            return GpuMetrics.unavailable("GPU Monitoring Disabled")
        if self._gpu_poller is not None:
            self._gpu_metrics = self._gpu_poller.latest_metrics()
            return self._gpu_metrics
        self._gpu_metrics = self._read_gpu_metrics()
        return self._gpu_metrics

    def _read_gpu_metrics(self) -> GpuMetrics:
        if not GPU_AVAILABLE or GPUtil is None:
            return GpuMetrics.unavailable("GPUtil Not Available")

        try:
            gpus = GPUtil.getGPUs()
            if not gpus:
                return GpuMetrics.unavailable("No GPU Found")

            gpu = gpus[0]
            return GpuMetrics(
                gpu_percent=gpu.load * 100,
                vram_percent=gpu.memoryUtil * 100,
                gpu_name=gpu.name,
                gpu_temp=self.config.gpu_temperature_sampling.project(
                    gpu.temperature
                ),
                vram_used_mb=gpu.memoryUsed,
                vram_total_mb=gpu.memoryTotal,
            )
        except Exception:
            return GpuMetrics.unavailable("GPU Error")

    def _initial_gpu_metrics(self) -> GpuMetrics:
        if not self.config.enable_gpu_monitoring:
            return GpuMetrics.unavailable("GPU Monitoring Disabled")
        return GpuMetrics.unavailable("GPU Pending")

    def close(self) -> None:
        """Stop any background metric providers owned by this sampler."""
        if self._cpu_frequency_poller is not None:
            self._cpu_frequency_poller.stop()
        if self._gpu_poller is not None:
            self._gpu_poller.stop()
