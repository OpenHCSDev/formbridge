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


class PublicationReceiver:
    """Subscription lifecycle management for a receiver of typed publications.

    A native carrier (Textual DOMNode, Qt QObject) composes this with its
    framework base. The shared receiver owns subscription tracking and
    observation; native hooks enqueue, invoke and stop native propagation.

    Consumed event types are read from MroDispatch handler declarations
    (metaclass-registry). The receiver never calls post_message or invoke.
    """

    def __init__(self) -> None:
        self._subscriptions: set[Subscription] = set()
        self._observations: dict[PublicationStream, tuple[Subscription, ...]] = {}

    def consumed_event_types(self, base_type: type) -> tuple[type, ...]:
        """Event types this receiver handles, filtered to a base type.
        Reads from MroDispatch._handler_declarations if the receiver
        inherits MroDispatch; otherwise returns an empty tuple."""
        declarations = getattr(type(self), "_handler_declarations", ())
        return tuple(dict.fromkeys(
            event for _name, classes in declarations
            for event in classes if issubclass(event, base_type)
        ))

    def subscribe_to(
        self,
        stream: PublicationStream,
        event_type: type,
        listener: Callable,
        **kwargs: object,
    ) -> Subscription:
        subscription = stream.subscribe(event_type, listener, **kwargs)
        self._subscriptions.add(subscription)
        return subscription

    def observe(self, stream: PublicationStream, base_type: type, listener: Callable) -> None:
        """Subscribe to every handled event type on this stream."""
        self._observations.setdefault(stream, tuple(
            stream.subscribe(event, listener) for event in self.consumed_event_types(base_type)
        ))

    def retire_subscription(self, subscription: Subscription) -> None:
        subscription.close()
        self._subscriptions.discard(subscription)

    def retire_observations(self, stream: PublicationStream) -> None:
        for subscription in self._observations.pop(stream, ()):
            subscription.close()
        for subscription in tuple(self._subscriptions):
            if subscription.stream is stream:
                self.retire_subscription(subscription)


class PublicationDelivery:
    """One publication carried to a receiver, retaining its emission-time publisher.

    A native carrier (Textual Message, Qt queued event) composes this with its
    native delivery base. The shared fields are the event, its subscription
    resource, the publisher at emission time, and a consume callback.
    """

    __slots__ = ("event", "subscription", "_publisher", "consume")

    def __init__(
        self,
        event: object,
        subscription: Subscription,
        consume: Callable = lambda receiver, delivery: None,
    ) -> None:
        self.event = event
        self.subscription = subscription
        self._publisher = subscription.stream.publisher
        self.consume = consume

    @property
    def publisher(self) -> object:
        return self._publisher

    def can_replace(self, other: PublicationDelivery) -> bool:
        """Whether this delivery replaces an adjacent queued one."""
        return (self.subscription is other.subscription
                and hasattr(self.event, "replaces")
                and self.event.replaces(other.event))
