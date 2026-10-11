"""Nominal configuration owner for the system monitor widget."""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import StrEnum

from python_introspect import validate_annotated_dataclass
from zmqruntime.config import PositiveFloat, PositiveInteger

from formbridge.services.system_metrics_sampler import SystemMetricsSamplerConfig


class PerformanceGraphColor(StrEnum):
    """Closed high-contrast palette offered for system-monitor graph series."""

    BLACK = "black"
    WHITE = "white"
    LIGHT_GRAY = "lightgray"
    GRAY = "gray"
    DARK_GRAY = "darkgray"
    RED = "red"
    DARK_RED = "darkred"
    ORANGE = "orange"
    YELLOW = "yellow"
    LIME = "lime"
    GREEN = "green"
    DARK_GREEN = "darkgreen"
    CYAN = "cyan"
    DARK_CYAN = "darkcyan"
    BLUE = "blue"
    DARK_BLUE = "darkblue"
    MAGENTA = "magenta"
    PURPLE = "purple"
    PINK = "pink"


@dataclass(frozen=True, slots=True)
class PerformanceMonitorColors:
    """Colors for the declared system-monitor series."""

    cpu: PerformanceGraphColor = PerformanceGraphColor.CYAN
    """Color used for the CPU utilization series."""

    ram: PerformanceGraphColor = PerformanceGraphColor.LIME
    """Color used for the system-memory series."""

    gpu: PerformanceGraphColor = PerformanceGraphColor.ORANGE
    """Color used for the GPU utilization series."""

    vram: PerformanceGraphColor = PerformanceGraphColor.MAGENTA
    """Color used for the GPU-memory series."""

    def __post_init__(self) -> None:
        validate_annotated_dataclass(self)


@dataclass(frozen=True)
class PerformanceMonitorConfig:
    """Complete behavior configuration for :class:`SystemMonitorWidget`."""

    update_fps: PositiveFloat = 10.0
    """Metric sampling and plot-update frequency in frames per second."""

    history_duration_seconds: PositiveFloat = 60.0
    """Duration of historical data displayed by the plots."""

    max_data_points: PositiveInteger | None = None
    """Explicit retained sample count, or ``None`` to derive it from time and FPS."""

    sampler_config: SystemMetricsSamplerConfig = field(default_factory=SystemMetricsSamplerConfig)
    """Policy owned by the system metrics sampler."""

    show_grid: bool = True
    """Whether monitor plots display grid lines."""

    antialiasing: bool = True
    """Whether plot curves request antialiased rendering."""

    use_opengl: bool = False
    """Whether plots request pyqtgraph's experimental OpenGL rendering path."""

    line_width: PositiveFloat = 2.0
    """Width of all monitor plot curves in pixels."""

    colors: PerformanceMonitorColors = field(default_factory=PerformanceMonitorColors)
    """Colors for the four declared monitor series."""

    def __post_init__(self) -> None:
        validate_annotated_dataclass(self)

    @property
    def update_interval_seconds(self) -> float:
        """Sampling interval derived from :attr:`update_fps`."""

        return 1.0 / self.update_fps

    @property
    def calculated_max_data_points(self) -> int:
        """Retained sample count derived from the declared history policy."""

        if self.max_data_points is not None:
            return self.max_data_points
        return max(
            1,
            int(self.history_duration_seconds / self.update_interval_seconds),
        )
