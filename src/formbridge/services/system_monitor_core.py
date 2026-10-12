"""
System Monitor Core - Framework-agnostic metrics collection.

This module provides pure system metrics collection without any visualization dependencies.
Can be used by any UI framework (PyQt, Textual, etc.) for system monitoring.
"""

import platform
import time
from collections import deque
from dataclasses import dataclass

import psutil

from formbridge.services.system_metrics_sampler import (
    GPU_AVAILABLE,
    CpuMetrics,
    GpuMetrics,
    GPUtil,
    MemoryMetrics,
    SystemMetrics,
    SystemMetricsSampler,
)


@dataclass(frozen=True, slots=True)
class SystemMetricsHistory:
    """Immutable history snapshot from one monitor."""

    cpu: tuple[float, ...]
    ram: tuple[float, ...]
    gpu: tuple[float, ...]
    vram: tuple[float, ...]
    timestamps: tuple[float, ...]


@dataclass(frozen=True, slots=True)
class SystemInformation:
    """Static host identity plus the canonical metrics carriers."""

    operating_system: str
    operating_system_version: str
    metrics: SystemMetrics


class SystemMonitorCore:
    """
    Framework-agnostic system monitoring core.

    Collects CPU, RAM, GPU, and VRAM metrics without any visualization dependencies.
    Maintains historical data in deques for efficient time-series tracking.
    """

    def __init__(
        self,
        history_length: int = 60,
        *,
        sampler: SystemMetricsSampler | None = None,
    ):
        """
        Initialize the system monitor core.

        Args:
            history_length: Number of historical data points to keep
        """
        self.history_length = history_length

        # Initialize data storage
        self.cpu_history = deque(maxlen=history_length)
        self.ram_history = deque(maxlen=history_length)
        self.gpu_history = deque(maxlen=history_length)
        self.vram_history = deque(maxlen=history_length)
        self.time_stamps = deque(maxlen=history_length)

        # Cache current metrics to avoid duplicate system calls
        self._current_metrics = SystemMetrics()
        self._sampler = sampler

        # Initialize with zeros
        for _ in range(history_length):
            self.cpu_history.append(0)
            self.ram_history.append(0)
            self.gpu_history.append(0)
            self.vram_history.append(0)
            self.time_stamps.append(0)

    def update_metrics(self) -> None:
        """
        Update system metrics and cache current values.

        Collects CPU, RAM, GPU, and VRAM usage and appends to history.
        Updates the typed internal cache for efficient access.
        """
        if self._sampler is None:
            self._sampler = SystemMetricsSampler()
        self.record_metrics(self._sampler.collect_metrics())

    def record_metrics(
        self,
        metrics: SystemMetrics,
        *,
        timestamp: float | None = None,
    ) -> None:
        """Record one canonical metrics snapshot in every history projection."""

        self.cpu_history.append(metrics.cpu.cpu_percent)
        self.ram_history.append(metrics.memory.ram_percent)
        self.gpu_history.append(metrics.gpu.gpu_percent)
        self.vram_history.append(metrics.gpu.vram_percent)
        self.time_stamps.append(time.time() if timestamp is None else timestamp)
        self._current_metrics = metrics

    def get_metrics(self) -> SystemMetrics:
        """Return the latest typed metrics snapshot without sampling again."""

        return self._current_metrics

    def get_history_data(self) -> SystemMetricsHistory:
        """Return one immutable projection of the owned history buffers."""

        return SystemMetricsHistory(
            cpu=tuple(self.cpu_history),
            ram=tuple(self.ram_history),
            gpu=tuple(self.gpu_history),
            vram=tuple(self.vram_history),
            timestamps=tuple(self.time_stamps),
        )

    def get_system_info(self) -> SystemInformation:
        """Return one typed static system-information snapshot."""

        gpu_metrics = GpuMetrics.unavailable("GPU Not Available")
        if GPU_AVAILABLE:
            try:
                gpus = GPUtil.getGPUs()
                if gpus:
                    gpu = gpus[0]
                    gpu_metrics = GpuMetrics(
                        gpu_percent=gpu.load * 100,
                        vram_percent=gpu.memoryUtil * 100,
                        gpu_name=gpu.name,
                        gpu_temp=gpu.temperature,
                        vram_used_mb=gpu.memoryUsed,
                        vram_total_mb=gpu.memoryTotal,
                    )
            except Exception:
                pass

        memory = psutil.virtual_memory()
        return SystemInformation(
            operating_system=platform.system(),
            operating_system_version=platform.version(),
            metrics=SystemMetrics(
                cpu=CpuMetrics(cpu_cores=psutil.cpu_count() or 0),
                memory=MemoryMetrics.from_psutil(memory),
                gpu=gpu_metrics,
            ),
        )

    def reset_history(self) -> None:
        """Reset all historical data to zeros."""
        self.cpu_history.clear()
        self.ram_history.clear()
        self.gpu_history.clear()
        self.vram_history.clear()
        self.time_stamps.clear()

        # Re-initialize with zeros
        for _ in range(self.history_length):
            self.cpu_history.append(0)
            self.ram_history.append(0)
            self.gpu_history.append(0)
            self.vram_history.append(0)
            self.time_stamps.append(0)

        self._current_metrics = SystemMetrics()

    def close(self) -> None:
        """Stop background metric providers owned by this monitor core."""
        if self._sampler is not None:
            self._sampler.close()
