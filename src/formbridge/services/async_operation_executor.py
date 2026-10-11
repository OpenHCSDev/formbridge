"""Owned execution of coroutine callables outside the Qt application thread."""

from __future__ import annotations

import asyncio
import threading
from collections.abc import Callable, Coroutine
from concurrent.futures import Future, ThreadPoolExecutor
from typing import Any, ParamSpec, TypeVar

ResultT = TypeVar("ResultT")
ParametersT = ParamSpec("ParametersT")


class AsyncOperationExecutorClosedError(RuntimeError):
    """Raised when work is submitted after executor shutdown begins."""


class AsyncOperationExecutor:
    """Own a worker pool and every coroutine operation submitted to it."""

    def __init__(self, *, max_workers: int = 4) -> None:
        self._executor = ThreadPoolExecutor(max_workers=max_workers)
        self._lock = threading.Lock()
        self._closed = False
        self._futures: set[Future] = set()

    def submit(
        self,
        async_callable: Callable[ParametersT, Coroutine[Any, Any, ResultT]],
        *args: ParametersT.args,
        **kwargs: ParametersT.kwargs,
    ) -> Future[ResultT]:
        """Submit one coroutine factory and retain its Future until completion."""

        with self._lock:
            if self._closed:
                raise AsyncOperationExecutorClosedError(
                    "Async operation executor is shutting down."
                )
            future = self._executor.submit(
                self._run_coroutine,
                async_callable,
                args,
                kwargs,
            )
            self._futures.add(future)
        future.add_done_callback(self._retire)
        return future

    def close(self) -> None:
        """Reject new work and cancel pending work.

        Operations which have already started remain owned in ``_futures`` until
        their completion callbacks retire them.  Shutdown deliberately does not
        wait: a coroutine may be blocked on a UI dispatcher which is itself being
        closed by the application thread.
        """

        with self._lock:
            if self._closed:
                return
            self._closed = True
            futures = tuple(self._futures)
        for future in futures:
            future.cancel()
        self._executor.shutdown(wait=False, cancel_futures=True)

    def active_futures(self) -> tuple[Future, ...]:
        """Return the exact unfinished operations currently owned."""

        with self._lock:
            return tuple(future for future in self._futures if not future.done())

    @staticmethod
    def _run_coroutine(async_callable, args, kwargs):
        loop = asyncio.new_event_loop()
        try:
            asyncio.set_event_loop(loop)
            return loop.run_until_complete(async_callable(*args, **kwargs))
        finally:
            asyncio.set_event_loop(None)
            loop.close()

    def _retire(self, future: Future) -> None:
        with self._lock:
            self._futures.discard(future)
