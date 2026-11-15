"""Generic publication and subscription, independent of any UI toolkit.

Moved from Toad's ``toad.core.events``. A subscriber owns a ``Subscription``
resource for as long as it wants publications. The stream snapshots matching
subscriptions before callbacks can subscribe or close, so a callback cannot
change the set being iterated.

Formbridge's existing ``WeakCallbackEvent`` provides the weak-listener
foundation; this module adds typed publication families, bucket-scoped
subscriptions and emission-time publisher retention.
"""

from __future__ import annotations

from dataclasses import InitVar, dataclass, field
from functools import cached_property
from typing import ClassVar
from weakref import WeakMethod, WeakSet, ref

from collections.abc import Callable


@dataclass(eq=False)
class Subscription:
    """A subscriber owns this resource for as long as it wants publications.

    The listener is a weak bound method: the subscription borrows its caller
    and never prevents its garbage collection. Closing discards the bucket
    entry; a dead listener closes automatically on next publish.
    """

    stream: PublicationStream
    event_type: type
    listener: InitVar[Callable]
    _listener: Callable[[], Callable | None] = field(init=False, repr=False)

    def __post_init__(self, listener: Callable) -> None:
        self._listener = WeakMethod(listener)

    def bucket_opened(self) -> None:
        """The first subscription for this event type was added."""

    def bucket_emptied(self) -> None:
        """The last subscription for this event type was removed."""

    @cached_property
    def bucket(self) -> WeakSet[Subscription]:
        return self.stream.subscriptions.setdefault(self.event_type, WeakSet())

    def listeners(self):
        listener = self._listener()
        if listener is None:
            self.close()
        elif self.active:
            yield listener

    @property
    def active(self) -> bool:
        return self in self.bucket

    def accepts(self, original: Subscription) -> bool:
        return self is original and self.active

    def close(self) -> None:
        if not self.active:
            return
        self.bucket.discard(self)
        if not self.bucket:
            self.bucket_emptied()

    def __enter__(self) -> Subscription:
        return self

    def __exit__(self, *exc: object) -> None:
        self.close()


class PublicationStream:
    """Publish events to subscribed listeners with snapshot-before-callback safety.

    The stream retains a weak reference to its publisher (the emission-time
    owner). Subscribe adds to a type-keyed bucket; publish snapshots matching
    subscriptions before invoking callbacks.
    """

    def __init__(self, publisher: object) -> None:
        self._publisher = ref(publisher)
        self.subscriptions: dict[type, WeakSet[Subscription]] = {}

    @property
    def publisher(self) -> object:
        publisher = self._publisher()
        if publisher is None:
            raise RuntimeError("The publication resource outlived its original owner")
        return publisher

    def subscribe(
        self,
        event_type: type,
        listener: Callable,
        *,
        factory: Callable[..., Subscription] = Subscription,
    ) -> Subscription:
        subscription = factory(self, event_type, listener)
        bucket = subscription.bucket
        first = not bucket
        bucket.add(subscription)
        if first:
            subscription.bucket_opened()
        return subscription

    def publish(self, event: object) -> None:
        """Notify live subscribers. Snapshot first so callbacks can subscribe/close."""
        subscriptions = tuple(self._matching_subscriptions(event))
        for subscription in subscriptions:
            for listener in subscription.listeners():
                listener(event, subscription)

    def _matching_subscriptions(self, event: object):
        """Subscriptions whose event type matches this event's MRO."""
        for event_type in type(event).__mro__:
            if bucket := self.subscriptions.get(event_type):
                yield from bucket
