from __future__ import annotations

import threading
from dataclasses import dataclass, fields, replace

import pytest

from formbridge.services import system_metrics_sampler as sampler_module
from formbridge.services.parameter_help_service import dataclass_parameter_descriptions
from formbridge.services.system_metrics_sampler import (
    BackgroundMetricPoller,
    CpuMetrics,
    GpuTemperatureSampling,
    GpuMetrics,
    MemoryMetrics,
    PollingCadence,
    PersistentNvidiaSmiPoller,
    SystemMetrics,
    SystemMetricsSampler,
    SystemMetricsSamplerConfig,
)


def test_sampler_config_projects_complete_declaration_help() -> None:
    descriptions = dataclass_parameter_descriptions(SystemMetricsSamplerConfig)
    field_names = {field.name for field in fields(SystemMetricsSamplerConfig)}

    assert set(descriptions) == field_names
    assert all(descriptions[name].strip() for name in field_names)
    assert "GPU utilization and memory metrics" in descriptions[
        "enable_gpu_monitoring"
    ]
    assert "interval in seconds" in descriptions["cpu_frequency_refresh_seconds"]


@dataclass(frozen=True, slots=True)
class MemorySnapshot:
    percent: float
    used: int
    total: int
    available: int


class FakeCpuFrequencyPoller:
    created: list["FakeCpuFrequencyPoller"] = []

    def __init__(self, *, name, cadence, probe, default) -> None:
        self.name = name
        self.cadence = cadence
        self.probe = probe
        self.default = default
        self.stopped = False
        self.__class__.created.append(self)

    def latest(self) -> int:
        return 2400

    def stop(self) -> None:
        self.stopped = True


class FakeGpuMetricsPoller:
    created: list["FakeGpuMetricsPoller"] = []

    def __init__(self, *, cadence, temperature_sampling) -> None:
        self.cadence = cadence
        self.temperature_sampling = temperature_sampling
        self.stopped = False
        self.__class__.created.append(self)

    def latest_metrics(self) -> GpuMetrics:
        return GpuMetrics(
            gpu_percent=12.5,
            vram_percent=25.0,
            gpu_name="Test GPU",
            gpu_temp=61.0,
            vram_used_mb=2048.0,
            vram_total_mb=8192.0,
        )

    def stop(self) -> None:
        self.stopped = True


def test_sampler_returns_typed_metrics_from_cached_background_providers(monkeypatch) -> None:
    FakeCpuFrequencyPoller.created.clear()
    FakeGpuMetricsPoller.created.clear()
    monkeypatch.setattr(sampler_module.psutil, "cpu_count", lambda: 16)
    monkeypatch.setattr(sampler_module.psutil, "cpu_percent", lambda interval=None: 7.5)
    monkeypatch.setattr(
        sampler_module.psutil,
        "virtual_memory",
        lambda: MemorySnapshot(
            percent=40.0,
            used=4 * 1024**3,
            total=16 * 1024**3,
            available=12 * 1024**3,
        ),
    )
    monkeypatch.setattr(sampler_module, "BackgroundMetricPoller", FakeCpuFrequencyPoller)
    monkeypatch.setattr(sampler_module, "PersistentNvidiaSmiPoller", FakeGpuMetricsPoller)

    config = SystemMetricsSamplerConfig(
        enable_gpu_monitoring=True,
        gpu_temperature_monitoring=True,
        cpu_frequency_monitoring=True,
        gpu_refresh_seconds=0.25,
        cpu_frequency_refresh_seconds=2.0,
    )
    sampler = SystemMetricsSampler(config)

    metrics = sampler.collect_metrics()

    assert isinstance(metrics, SystemMetrics)
    assert metrics.cpu == CpuMetrics(
        cpu_percent=7.5,
        cpu_cores=16,
        cpu_freq_mhz=2400,
    )
    assert metrics.memory == MemoryMetrics(
        ram_percent=40.0,
        ram_used_gb=4.0,
        ram_total_gb=16.0,
        ram_available_gb=12.0,
    )
    assert metrics.gpu.gpu_name == "Test GPU"
    assert metrics.gpu.vram_percent == 25.0
    assert metrics.gpu.gpu_percent == 12.5
    assert FakeCpuFrequencyPoller.created[0].cadence == PollingCadence(2.0)
    assert FakeGpuMetricsPoller.created[0].cadence == PollingCadence(0.25)

    sampler.close()

    assert FakeCpuFrequencyPoller.created[0].stopped is True
    assert FakeGpuMetricsPoller.created[0].stopped is True


def test_nvidia_smi_poller_parses_typed_metrics() -> None:
    poller = PersistentNvidiaSmiPoller(
        cadence=PollingCadence(0.5),
        temperature_sampling=GpuTemperatureSampling.ENABLED,
    )

    metrics = poller._parse_gpu_line("12, 63, 2048, 8192, NVIDIA RTX")

    assert metrics == GpuMetrics(
        gpu_percent=12.0,
        vram_percent=25.0,
        gpu_name="NVIDIA RTX",
        gpu_temp=63.0,
        vram_used_mb=2048.0,
        vram_total_mb=8192.0,
    )


def test_nvidia_smi_poller_respects_temperature_policy() -> None:
    poller = PersistentNvidiaSmiPoller(
        cadence=PollingCadence(0.5),
        temperature_sampling=GpuTemperatureSampling.DISABLED,
    )

    metrics = poller._parse_gpu_line("12, 63, 2048, 8192, NVIDIA RTX")

    assert metrics.gpu_temp == 0


def test_enable_gpu_monitoring_leaf_disables_gpu_provider(monkeypatch) -> None:
    monkeypatch.setattr(sampler_module, "PersistentNvidiaSmiPoller", FakeGpuMetricsPoller)
    config = replace(SystemMetricsSamplerConfig(), enable_gpu_monitoring=False)

    sampler = SystemMetricsSampler(config)

    assert sampler._gpu_poller is None
    assert sampler._cached_gpu_metrics().gpu_name == "GPU Monitoring Disabled"
    sampler.close()


def test_gpu_temperature_monitoring_leaf_reaches_gpu_provider(monkeypatch) -> None:
    FakeGpuMetricsPoller.created.clear()
    monkeypatch.setattr(sampler_module, "PersistentNvidiaSmiPoller", FakeGpuMetricsPoller)
    config = replace(SystemMetricsSamplerConfig(), gpu_temperature_monitoring=False)

    sampler = SystemMetricsSampler(config)

    assert (
        FakeGpuMetricsPoller.created[-1].temperature_sampling
        is GpuTemperatureSampling.DISABLED
    )
    sampler.close()


def test_cpu_frequency_monitoring_leaf_disables_frequency_provider(monkeypatch) -> None:
    monkeypatch.setattr(sampler_module, "BackgroundMetricPoller", FakeCpuFrequencyPoller)
    config = replace(SystemMetricsSamplerConfig(), cpu_frequency_monitoring=False)

    sampler = SystemMetricsSampler(config)

    assert sampler._cpu_frequency_poller is None
    assert sampler._cached_cpu_frequency() == 0
    sampler.close()


def test_gpu_refresh_seconds_leaf_reaches_gpu_provider(monkeypatch) -> None:
    FakeGpuMetricsPoller.created.clear()
    monkeypatch.setattr(sampler_module, "PersistentNvidiaSmiPoller", FakeGpuMetricsPoller)
    config = replace(SystemMetricsSamplerConfig(), gpu_refresh_seconds=0.25)

    sampler = SystemMetricsSampler(config)

    assert FakeGpuMetricsPoller.created[-1].cadence == PollingCadence(0.25)
    sampler.close()


def test_cpu_frequency_refresh_seconds_leaf_reaches_frequency_provider(
    monkeypatch,
) -> None:
    FakeCpuFrequencyPoller.created.clear()
    monkeypatch.setattr(sampler_module, "BackgroundMetricPoller", FakeCpuFrequencyPoller)
    config = replace(SystemMetricsSamplerConfig(), cpu_frequency_refresh_seconds=2.0)

    sampler = SystemMetricsSampler(config)

    assert FakeCpuFrequencyPoller.created[-1].cadence == PollingCadence(2.0)
    sampler.close()


def test_background_metric_poller_is_lazy_and_does_not_restart_after_stop() -> None:
    probe_called = threading.Event()

    def probe() -> int:
        probe_called.set()
        return 3200

    poller = BackgroundMetricPoller(
        name="TestMetricPoller",
        cadence=PollingCadence(60.0),
        probe=probe,
        default=0,
    )

    assert probe_called.is_set() is False
    assert poller.latest() in {0, 3200}
    assert probe_called.wait(timeout=1.0) is True
    assert poller.latest() == 3200

    poller.stop()
    probe_called.clear()

    assert poller.latest() == 3200
    assert probe_called.is_set() is False


@pytest.mark.parametrize(
    "config_kwargs",
    (
        {"gpu_refresh_seconds": 0},
        {"cpu_frequency_refresh_seconds": 0},
    ),
)
def test_sampler_config_rejects_nonpositive_refresh_intervals(config_kwargs) -> None:
    with pytest.raises(ValueError):
        SystemMetricsSamplerConfig(**config_kwargs)
