"""Owned dispatch of callable work onto one owner thread.

A dispatcher owns every callable queued onto its owner thread until the callable
runs or is cancelled. Subclasses say which thread owns the work and how a queued
call reaches it: a toolkit event loop (pyqt-reactive's ``UiThreadDispatcher``)
or :class:`QueuedMainThreadDispatcher`, which a headless process drains itself.
"""

from __future__ import annotations

import queue
import threading
from abc import ABC, abstractmethod
from collections.abc import Callable
from concurrent.futures import Future
from typing import Generic, TypeVar, cast

ResultT = TypeVar("ResultT")


class MainThreadDispatchError(RuntimeError):
    """Raised when an operation cannot be dispatched to the owner thread."""


class MainThreadDispatcherClosedError(MainThreadDispatchError):
    """Raised when dispatch is requested after shutdown begins."""


class MainThreadDispatchTimeoutError(TimeoutError):
    """Raised when a queued operation does not begin in time."""


class DispatchedCall(Generic[ResultT]):
    """One callable owned by a dispatcher until execution or cancellation."""

    def __init__(
        self,
        callback: Callable[[], ResultT],
        retire: Callable[[DispatchedCall[ResultT]], None],
    ) -> None:
        self._callback = callback
        self._retire = retire
        self._lock = threading.Lock()
        self._started = False
        self._finished = False
        self.done = threading.Event()
        self.result: ResultT | None = None
        self.error: BaseException | None = None

    def run(self) -> None:
        with self._lock:
            if self._finished:
                return
            self._started = True
        try:
            result = self._callback()
        except BaseException as error:
            self._finish(error=error)
        else:
            self._finish(result=result)

    def cancel(self, error: BaseException) -> bool:
        with self._lock:
            if self._started or self._finished:
                return False
            self._finished = True
            self.error = error
        self._complete()
        return True

    def _finish(
        self,
        *,
        result: ResultT | None = None,
        error: BaseException | None = None,
    ) -> None:
        with self._lock:
            if self._finished:
                return
            self._finished = True
            self.result = result
            self.error = error
        self._complete()

    def _complete(self) -> None:
        self.done.set()
        self._retire(self)


class MainThreadDispatcher(ABC):
    """Own every callable queued onto the owner thread."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._closed = False
        self._calls: set[DispatchedCall] = set()

    @abstractmethod
    def _is_owner_thread(self) -> bool:
        """Return whether the calling thread owns dispatched work."""

    @abstractmethod
    def _can_deliver(self) -> bool:
        """Return whether a queued call can reach the owner thread."""

    @abstractmethod
    def _deliver(self, call: DispatchedCall) -> None:
        """Hand one registered call to the owner thread."""

    def _undeliverable_error(self) -> MainThreadDispatchError:
        return MainThreadDispatchError("No owner thread is available for dispatch.")

    def close(self) -> None:
        """Reject new work and cancel callbacks which have not begun."""

        with self._lock:
            if self._closed:
                return
            self._closed = True
            calls = tuple(self._calls)
        for call in calls:
            call.cancel(MainThreadDispatcherClosedError("Dispatcher is shutting down."))

    def call(
        self,
        callback: Callable[[], ResultT],
        *,
        timeout_ms: int = 5000,
    ) -> ResultT:
        """Run on the owner thread and return its one authoritative outcome."""

        if self._is_owner_thread():
            self._require_open()
            return callback()
        if not self._can_deliver():
            raise self._undeliverable_error()

        call = self._register(callback)
        self._deliver(call)
        if not call.done.wait(timeout_ms / 1000):
            timeout = self._dispatch_timeout_error()
            if call.cancel(timeout):
                raise timeout
            call.done.wait()
        if call.error is not None:
            raise call.error
        return cast(ResultT, call.result)

    @staticmethod
    def _dispatch_timeout_error() -> MainThreadDispatchTimeoutError:
        """Construct the outcome offered only to a not-yet-started call.

        The call's atomic cancel() decides whether this error is published.
        Started callbacks retain their own outcome, even when that outcome is
        itself a MainThreadDispatchTimeoutError. Subclasses can project the owned
        cancellation without catching and misclassifying callback exceptions.
        """
        return MainThreadDispatchTimeoutError("Timed out waiting for owner-thread dispatch.")

    def post(self, callback: Callable[[], None]) -> None:
        """Queue work on the owner thread without waiting for its result."""

        if not self._can_deliver():
            if self._is_owner_thread():
                self._require_open()
                callback()
                return
            raise self._undeliverable_error()
        self._deliver(self._register(callback))

    def _register(self, callback: Callable[[], ResultT]) -> DispatchedCall[ResultT]:
        with self._lock:
            if self._closed:
                raise MainThreadDispatcherClosedError("Dispatcher is shutting down.")
            call = DispatchedCall(callback, self._retire)
            self._calls.add(call)
            return call

    def _retire(self, call: DispatchedCall) -> None:
        with self._lock:
            self._calls.discard(call)

    def _require_open(self) -> None:
        with self._lock:
            if self._closed:
                raise MainThreadDispatcherClosedError("Dispatcher is shutting down.")


class _Wake:
    """Queue item that ends one ``run_until`` wait when its future completes."""


class QueuedMainThreadDispatcher(MainThreadDispatcher):
    """Dispatch onto the thread that built this dispatcher, drained by ``run_until``.

    A headless process has no toolkit event loop; its owner thread runs
    ``run_until(future)`` and executes queued calls until the future completes.
    """

    def __init__(self) -> None:
        super().__init__()
        self._owner = threading.current_thread()
        self._queue: queue.SimpleQueue[DispatchedCall | _Wake] = queue.SimpleQueue()

    def _is_owner_thread(self) -> bool:
        return threading.current_thread() is self._owner

    def _can_deliver(self) -> bool:
        return True

    def _deliver(self, call: DispatchedCall) -> None:
        self._queue.put(call)

    def run_until(self, future: Future) -> None:
        """Run queued calls on the owner thread until ``future`` completes."""

        if not self._is_owner_thread():
            raise MainThreadDispatchError("run_until must be called on the owner thread.")
        wake = _Wake()
        future.add_done_callback(lambda _completed: self._queue.put(wake))
        while not future.done():
            item = self._queue.get()
            if item is wake:
                return
            if isinstance(item, DispatchedCall):
                item.run()
