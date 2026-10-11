"""Ownership tests for coroutine worker execution."""

from __future__ import annotations

import asyncio
import threading

import pytest

from formbridge.services.async_operation_executor import (
    AsyncOperationExecutor,
    AsyncOperationExecutorClosedError,
)


def test_executor_retains_operation_until_completion() -> None:
    executor = AsyncOperationExecutor(max_workers=1)
    release = threading.Event()

    async def operation() -> str:
        await asyncio.get_running_loop().run_in_executor(None, release.wait)
        return "done"

    future = executor.submit(operation)

    assert executor.active_futures() == (future,)
    release.set()
    assert future.result(timeout=1.0) == "done"
    assert executor.active_futures() == ()
    executor.close()


def test_executor_closes_event_loop_after_operation_failure(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    executor = AsyncOperationExecutor(max_workers=1)
    loops = []
    real_new_event_loop = asyncio.new_event_loop

    def recorded_loop():
        loop = real_new_event_loop()
        loops.append(loop)
        return loop

    monkeypatch.setattr(asyncio, "new_event_loop", recorded_loop)

    async def fail() -> None:
        raise RuntimeError("failed")

    with pytest.raises(RuntimeError, match="failed"):
        executor.submit(fail).result(timeout=1.0)

    assert len(loops) == 1
    assert loops[0].is_closed()
    executor.close()


def test_close_cancels_queued_work_and_rejects_new_submissions() -> None:
    executor = AsyncOperationExecutor(max_workers=1)
    started = threading.Event()
    release = threading.Event()
    queued_ran: list[bool] = []

    async def blocking() -> None:
        started.set()
        await asyncio.get_running_loop().run_in_executor(None, release.wait)

    async def queued() -> None:
        queued_ran.append(True)

    running = executor.submit(blocking)
    assert started.wait(timeout=1.0)
    pending = executor.submit(queued)

    executor.close()
    assert executor.active_futures() == (running,)
    assert pending.cancelled()
    with pytest.raises(AsyncOperationExecutorClosedError):
        executor.submit(queued)

    release.set()
    running.result(timeout=1.0)
    assert queued_ran == []
