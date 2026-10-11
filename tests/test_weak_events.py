"""Exact weak subscription ownership and immutable notification snapshots."""

import gc
import weakref

from formbridge.weak_events import WeakCallbackEvent, WeakSubscription


class Subscriber:
    def __init__(self, observations):
        self.observations = observations

    def observe(self, value):
        self.observations.append(value)


def test_subscription_token_owns_neither_event_nor_callback():
    event = WeakCallbackEvent()
    subscriber = Subscriber([])
    event_reference = weakref.ref(event)
    subscriber_reference = weakref.ref(subscriber)
    token = event.subscribe(subscriber.observe)
    assert isinstance(token, WeakSubscription)
    assert weakref.ref(token)() is token
    del event, subscriber
    gc.collect()
    assert event_reference() is None
    assert subscriber_reference() is None
    token.cancel()


def test_duplicate_callback_returns_exact_same_cancellation_token():
    event = WeakCallbackEvent()
    observations = []
    subscriber = Subscriber(observations)
    token = event.subscribe(subscriber.observe)
    assert event.subscribe(subscriber.observe) is token
    event.emit("changed")
    assert observations == ["changed"]
    token.cancel()
    token.cancel()
    event.emit("cancelled")
    assert observations == ["changed"]


def test_old_token_cannot_cancel_callback_registered_again():
    event = WeakCallbackEvent()
    observations = []
    subscriber = Subscriber(observations)
    old = event.subscribe(subscriber.observe)
    old.cancel()
    current = event.subscribe(subscriber.observe)
    assert current is not old
    old.cancel()
    event.emit("changed")
    assert observations == ["changed"]


def test_cancel_uses_identity_not_equal_callback_comparison():
    class EqualSubscriber(Subscriber):
        def __eq__(self, other):
            return isinstance(other, EqualSubscriber)

    event = WeakCallbackEvent()
    observations = []
    first = EqualSubscriber(observations)
    second = EqualSubscriber(observations)
    token = event.subscribe(first.observe)
    event.subscribe(second.observe)
    token.cancel()
    event.emit("changed")
    assert observations == ["changed"]


def test_cancellation_during_emit_preserves_emission_start_snapshot():
    event = WeakCallbackEvent()
    observations = []

    def first(value):
        observations.append(("first", value))
        second_token.cancel()

    def second(value):
        observations.append(("second", value))

    event.subscribe(first)
    second_token = event.subscribe(second)
    event.emit(1)
    event.emit(2)
    assert observations == [("first", 1), ("second", 1), ("first", 2)]


def test_token_can_cancel_dead_callback_without_resolving_it():
    event = WeakCallbackEvent()
    subscriber = Subscriber([])
    token = event.subscribe(subscriber.observe)
    del subscriber
    gc.collect()
    assert token.callback_reference() is None
    token.cancel()
    event.emit("changed")
