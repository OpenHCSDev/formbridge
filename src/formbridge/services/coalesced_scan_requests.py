"""Concurrency gate for invalidation-driven background scans."""

from __future__ import annotations

import threading


class CoalescedScanRequests:
    """Single authority for one active scan and any newer invalidations."""

    def __init__(self) -> None:
        self._outstanding = 0
        self._lock = threading.Lock()

    def request(self) -> bool:
        """Record an invalidation and report whether its scan must start now."""

        with self._lock:
            self._outstanding += 1
            return self._outstanding == 1

    def complete(self) -> bool:
        """Complete the active scan and retain at most one follow-up request."""

        with self._lock:
            follow_up_required = self._outstanding > 1
            self._outstanding = 1 if follow_up_required else 0
            return follow_up_required

    def clear(self) -> None:
        """Discard all outstanding work when its owner lifecycle ends."""

        with self._lock:
            self._outstanding = 0

    def has_outstanding(self) -> bool:
        """Return whether a scan or a coalesced follow-up is outstanding."""

        with self._lock:
            return self._outstanding > 0
