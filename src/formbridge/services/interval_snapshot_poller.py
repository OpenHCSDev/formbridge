"""Generic interval-based background snapshot poller."""

from __future__ import annotations

import threading
import time
from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import Callable, Generic, TypeVar


TSnapshot = TypeVar("TSnapshot")


class IntervalSnapshotPollerPolicyABC(ABC, Generic[TSnapshot]):
    """Policy boundary for background polling behavior."""

    @abstractmethod
    def fetch_snapshot(self) -> TSnapshot:
        """Fetch latest snapshot from source."""

    @abstractmethod
    def clone_snapshot(self, snapshot: TSnapshot) -> TSnapshot:
        """Return an isolated clone of one snapshot value."""

    @property
    def poll_interval_seconds(self) -> float:
        return 1.0

    def on_snapshot_changed(self, snapshot: TSnapshot) -> None:
        pass

    def on_poll_error(self, error: Exception) -> None:
        pass


@dataclass(frozen=True)
class CallbackIntervalSnapshotPollerPolicy(
    IntervalSnapshotPollerPolicyABC[TSnapshot], Generic[TSnapshot]
):
    """Callback-backed interval polling policy."""

    fetch_snapshot_fn: Callable[[], TSnapshot]
    clone_snapshot_fn: Callable[[TSnapshot], TSnapshot]
    poll_interval_seconds_value: float = 1.0
    on_snapshot_changed_fn: Callable[[TSnapshot], None] | None = None
    on_poll_error_fn: Callable[[Exception], None] | None = None

    def fetch_snapshot(self) -> TSnapshot:
        return self.fetch_snapshot_fn()

    def clone_snapshot(self, snapshot: TSnapshot) -> TSnapshot:
        return self.clone_snapshot_fn(snapshot)

    @property
    def poll_interval_seconds(self) -> float:
        return self.poll_interval_seconds_value

    def on_snapshot_changed(self, snapshot: TSnapshot) -> None:
        if self.on_snapshot_changed_fn is not None:
            self.on_snapshot_changed_fn(snapshot)

    def on_poll_error(self, error: Exception) -> None:
        if self.on_poll_error_fn is not None:
            self.on_poll_error_fn(error)


class IntervalSnapshotPoller(Generic[TSnapshot]):
    """Runs at most one background poll at a configured interval."""

    def __init__(
        self,
        policy: IntervalSnapshotPollerPolicyABC[TSnapshot],
    ) -> None:
        self._policy = policy
        self._lock = threading.Lock()
        self._snapshot: TSnapshot | None = None
        self._inflight = False
        self._inflight_generation: int | None = None
        self._last_poll_ts = 0.0
        self._generation = 0

    def tick(self) -> None:
        """Schedule one background poll if interval and inflight gates allow it."""
        now = time.time()
        with self._lock:
            if self._inflight:
                return
            if now - self._last_poll_ts < self._policy.poll_interval_seconds:
                return
            self._inflight = True
            self._last_poll_ts = now
            generation = self._generation
            self._inflight_generation = generation

        threading.Thread(
            target=self._poll_worker,
            args=(generation,),
            daemon=True,
        ).start()

    def get_snapshot_copy(self) -> TSnapshot | None:
        """Read the current snapshot using policy clone semantics."""
        with self._lock:
            if self._snapshot is None:
                return None
            return self._policy.clone_snapshot(self._snapshot)

    def is_poll_inflight(self) -> bool:
        with self._lock:
            return self._inflight

    def reset(self) -> None:
        """Drop current snapshot and invalidate any in-flight worker result."""
        with self._lock:
            self._snapshot = None
            self._last_poll_ts = 0.0
            self._generation += 1

    def _poll_worker(self, generation: int) -> None:
        try:
            snapshot = self._policy.fetch_snapshot()
            changed = False
            with self._lock:
                if generation != self._generation:
                    return
                changed = snapshot != self._snapshot
                self._snapshot = snapshot
            if changed:
                self._policy.on_snapshot_changed(self._policy.clone_snapshot(snapshot))
        except Exception as error:
            self._policy.on_poll_error(error)
        finally:
            with self._lock:
                if self._inflight_generation == generation:
                    self._inflight = False
                    self._inflight_generation = None
