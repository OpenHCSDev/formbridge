"""Background helpers launch through zmqruntime's background process policy."""

from __future__ import annotations

from types import SimpleNamespace

from formbridge.services import system_metrics_sampler
from formbridge.utils import log_highlight_client


class _ConsumerLaunchPolicy:
    @classmethod
    def current(cls, *, detached=False):
        assert detached is False
        return SimpleNamespace(
            popen_arguments=lambda: {"creationflags": 73},
            python_executable=lambda _executable: "windowed-python",
        )


def test_system_metric_helpers_use_background_process_policy(monkeypatch) -> None:
    check_output_calls: list[dict[str, object]] = []
    popen_calls: list[dict[str, object]] = []
    process = SimpleNamespace(stdout=())

    monkeypatch.setattr(system_metrics_sampler, "is_wsl", lambda: True)
    monkeypatch.setattr(
        system_metrics_sampler,
        "BackgroundProcessLaunchPolicy",
        _ConsumerLaunchPolicy,
    )
    monkeypatch.setattr(
        system_metrics_sampler.subprocess,
        "check_output",
        lambda _command, **kwargs: check_output_calls.append(kwargs) or b"2400",
    )
    monkeypatch.setattr(
        system_metrics_sampler.shutil,
        "which",
        lambda _name: "nvidia-smi",
    )
    monkeypatch.setattr(
        system_metrics_sampler.subprocess,
        "Popen",
        lambda _command, **kwargs: popen_calls.append(kwargs) or process,
    )
    monkeypatch.setattr(
        system_metrics_sampler.threading,
        "Thread",
        lambda **_kwargs: SimpleNamespace(start=lambda: None),
    )

    assert system_metrics_sampler.get_cpu_freq_mhz() == 2400
    system_metrics_sampler.PersistentNvidiaSmiPoller(
        cadence=system_metrics_sampler.PollingCadence(1.0),
        temperature_sampling=(system_metrics_sampler.GpuTemperatureSampling.ENABLED),
    ).start()

    assert check_output_calls[0]["creationflags"] == 73
    assert popen_calls[0]["creationflags"] == 73


def test_log_highlighter_uses_background_process_policy(monkeypatch) -> None:
    captured: dict[str, object] = {}
    process = SimpleNamespace(
        poll=lambda: None,
        terminate=lambda: None,
        wait=lambda timeout=None: None,
    )
    monkeypatch.setattr(
        log_highlight_client,
        "BackgroundProcessLaunchPolicy",
        _ConsumerLaunchPolicy,
    )
    monkeypatch.setattr(
        log_highlight_client.subprocess,
        "Popen",
        lambda command, **kwargs: captured.update(command=command, **kwargs) or process,
    )
    client = log_highlight_client.LogHighlightClient()
    try:
        assert client._ensure_process() is process
        assert captured["command"][0] == "windowed-python"
        assert captured["creationflags"] == 73
    finally:
        client.shutdown()
