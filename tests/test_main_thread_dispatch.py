"""The queued dispatcher runs work on its owner thread only, with owned cancellation."""

from __future__ import annotations

import threading
from concurrent.futures import Future, ThreadPoolExecutor

import pytest

from formbridge.services.main_thread_dispatch import (
    MainThreadDispatcherClosedError,
    MainThreadDispatchError,
    MainThreadDispatchTimeoutError,
    QueuedMainThreadDispatcher,
)


def test_worker_call_runs_on_owner_thread_while_owner_drains() -> None:
    dispatcher = QueuedMainThreadDispatcher()
    owner = threading.current_thread()
    with ThreadPoolExecutor(max_workers=1) as pool:
        future = pool.submit(dispatcher.call, threading.current_thread)
        dispatcher.run_until(future)
    assert future.result() is owner


def test_owner_call_runs_inline() -> None:
    dispatcher = QueuedMainThreadDispatcher()
    assert dispatcher.call(lambda: "inline") == "inline"


def test_undrained_call_is_cancelled_before_it_starts() -> None:
    dispatcher = QueuedMainThreadDispatcher()
    calls: list[str] = []
    errors: list[BaseException] = []

    def from_worker() -> None:
        try:
            dispatcher.call(lambda: calls.append("late"), timeout_ms=10)
        except BaseException as error:
            errors.append(error)

    worker = threading.Thread(target=from_worker)
    worker.start()
    worker.join(timeout=2)
    finished: Future[None] = Future()
    finished.set_result(None)
    dispatcher.run_until(finished)

    assert calls == []
    assert [type(error) for error in errors] == [MainThreadDispatchTimeoutError]


def test_started_callback_keeps_its_own_outcome() -> None:
    dispatcher = QueuedMainThreadDispatcher()
    original = MainThreadDispatchTimeoutError("raised by the callback itself")

    def callback() -> None:
        raise original

    with ThreadPoolExecutor(max_workers=1) as pool:
        future = pool.submit(dispatcher.call, callback)
        dispatcher.run_until(future)
    with pytest.raises(MainThreadDispatchTimeoutError) as caught:
        future.result()
    assert caught.value is original


def test_close_cancels_posted_work_and_rejects_new_work() -> None:
    dispatcher = QueuedMainThreadDispatcher()
    calls: list[str] = []
    dispatcher.post(lambda: calls.append("late"))
    dispatcher.close()
    finished: Future[None] = Future()
    finished.set_result(None)
    dispatcher.run_until(finished)

    assert calls == []
    with pytest.raises(MainThreadDispatcherClosedError):
        dispatcher.post(lambda: None)


def test_run_until_belongs_to_the_owner_thread() -> None:
    dispatcher = QueuedMainThreadDispatcher()
    future: Future[None] = Future()
    with ThreadPoolExecutor(max_workers=1) as pool:
        with pytest.raises(MainThreadDispatchError):
            pool.submit(dispatcher.run_until, future).result()
