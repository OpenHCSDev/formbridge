"""Weak callback notifications with exact, non-owning cancellation handles.

This module does not import Qt. A QObject can connect ``destroyed`` to a
subscription's ``cancel`` without its cleanup callback retaining that QObject.
"""

from __future__ import annotations

import threading
from collections.abc import Callable
from dataclasses import dataclass
from types import MethodType
from typing import Generic, ParamSpec
from weakref import ReferenceType, WeakMethod, ref

P = ParamSpec("P")


@dataclass(frozen=True, eq=False)
class WeakSubscription(Generic[P]):
    """Exact registration identity, owning neither callback nor event lifetime."""

    event_reference: ReferenceType[WeakCallbackEvent[P]]
    callback_reference: ReferenceType[Callable[P, None]]

    def cancel(self) -> None:
        """Cancel only this registration, including after its callback dies."""
        event = self.event_reference()
        if event is not None:
            event._cancel_subscription(self)


class WeakCallbackEvent(Generic[P]):
    """Thread-safe weak event with an immutable emission-start snapshot.

    Subscribers must own their callbacks elsewhere. Repeated registration of
    the same callback returns the same token. Cancellation is idempotent and
    cannot cancel a later registration of that callback. Changes during an
    emission take effect on the next emission, not its existing snapshot.
    """

    def __init__(self) -> None:
        self._subscribers: list[WeakSubscription[P]] = []
        self._lock = threading.RLock()

    @staticmethod
    def _is_same_callback(left: Callable[P, None], right: Callable[P, None]) -> bool:
        if isinstance(left, MethodType) and isinstance(right, MethodType):
            return left.__self__ is right.__self__ and left.__func__ is right.__func__
        return left is right

    def subscribe(self, callback: Callable[P, None]) -> WeakSubscription[P]:
        """Observe a callback and return its non-owning cancellation token."""
        with self._lock:
            live_subscriptions: list[WeakSubscription[P]] = []
            existing: WeakSubscription[P] | None = None
            for subscription in self._subscribers:
                subscriber = subscription.callback_reference()
                if subscriber is None:
                    continue
                live_subscriptions.append(subscription)
                if self._is_same_callback(subscriber, callback):
                    existing = subscription
            if existing is None:
                existing = WeakSubscription(
                    event_reference=ref(self),
                    callback_reference=(
                        WeakMethod(callback) if isinstance(callback, MethodType) else ref(callback)
                    ),
                )
                live_subscriptions.append(existing)
            self._subscribers = live_subscriptions
            return existing

    def _cancel_subscription(self, cancelled: WeakSubscription[P]) -> None:
        with self._lock:
            self._subscribers = [
                subscription
                for subscription in self._subscribers
                if subscription is not cancelled and subscription.callback_reference() is not None
            ]

    def unsubscribe(self, callback: Callable[P, None]) -> None:
        """Cancel the current registration of one exact callback identity."""
        with self._lock:
            self._subscribers = [
                subscription
                for subscription in self._subscribers
                if (subscriber := subscription.callback_reference()) is not None
                and not self._is_same_callback(subscriber, callback)
            ]

    def emit(self, *args: P.args, **kwargs: P.kwargs) -> None:
        """Notify live callbacks captured at emission start."""
        with self._lock:
            live_subscriptions: list[WeakSubscription[P]] = []
            subscribers: list[Callable[P, None]] = []
            for subscription in self._subscribers:
                subscriber = subscription.callback_reference()
                if subscriber is None:
                    continue
                live_subscriptions.append(subscription)
                subscribers.append(subscriber)
            self._subscribers = live_subscriptions
        for subscriber in subscribers:
            subscriber(*args, **kwargs)
