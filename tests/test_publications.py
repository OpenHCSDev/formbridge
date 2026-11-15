"""PublicationStream and Subscription own shared pub/sub behavior."""

import gc
from formbridge.publications import (
    PublicationStream,
    PublicationDelivery,
    PublicationReceiver,
    Subscription,
)


class Publisher:
    """A weakref-able publisher for tests (bare object() can't be weakref'd)."""


class Listener:
    def __init__(self):
        self.received = []

    def on_event(self, event, subscription):
        self.received.append(event)


def test_subscribe_and_publish():
    publisher = Publisher()
    stream = PublicationStream(publisher)
    listener = Listener()
    sub = stream.subscribe(str, listener.on_event)
    stream.publish("hello")
    assert listener.received == ["hello"]
    assert sub.active


def test_subscription_close():
    publisher = Publisher()
    stream = PublicationStream(publisher)
    listener = Listener()
    sub = stream.subscribe(str, listener.on_event)
    sub.close()
    stream.publish("after close")
    assert listener.received == []


def test_subscription_context_manager():
    publisher = Publisher()
    stream = PublicationStream(publisher)
    listener = Listener()
    with stream.subscribe(str, listener.on_event):
        stream.publish("inside")
    stream.publish("outside")
    assert listener.received == ["inside"]


def test_weak_listener_collected():
    publisher = Publisher()
    stream = PublicationStream(publisher)
    listener = Listener()
    stream.subscribe(str, listener.on_event)
    del listener
    gc.collect()
    stream.publish("after gc")


def test_mro_matching():
    class Base: pass
    class Child(Base): pass

    publisher = Publisher()
    stream = PublicationStream(publisher)
    listener = Listener()
    sub = stream.subscribe(Base, listener.on_event)
    stream.publish(Child())
    assert len(listener.received) == 1
    assert isinstance(listener.received[0], Child)
    assert sub.active


def test_publisher_retained_on_delivery():
    publisher = Publisher()
    stream = PublicationStream(publisher)
    listener = Listener()
    sub = stream.subscribe(str, listener.on_event)
    delivery = PublicationDelivery("event", sub)
    assert delivery.publisher is publisher


def test_delivery_can_replace():
    class Replaceable:
        def __init__(self, key):
            self.key = key
        def replaces(self, other):
            return self.key == other.key

    publisher = Publisher()
    stream = PublicationStream(publisher)
    listener = Listener()
    sub = stream.subscribe(Replaceable, listener.on_event)
    d1 = PublicationDelivery(Replaceable("a"), sub)
    d2 = PublicationDelivery(Replaceable("a"), sub)
    d3 = PublicationDelivery(Replaceable("b"), sub)
    assert d2.can_replace(d1)
    assert not d3.can_replace(d1)


def test_bucket_opened_called_on_first_subscribe():
    opened = []

    class TrackingSubscription(Subscription):
        def bucket_opened(self):
            opened.append(True)

    publisher = Publisher()
    stream = PublicationStream(publisher)
    listener = Listener()
    sub1 = stream.subscribe(str, listener.on_event, factory=TrackingSubscription)
    assert len(opened) == 1
    sub2 = stream.subscribe(str, listener.on_event, factory=TrackingSubscription)
    assert len(opened) == 1
    assert sub1.active and sub2.active
