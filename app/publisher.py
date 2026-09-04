"""Event transport for the outbox relay.

The relay reads unpublished rows, hands them to a transport, and only marks a
row published once the transport has accepted it. If the transport fails the
row stays pending and is retried, so delivery is at-least-once and consumers
must deduplicate on event_id.
"""

import logging
import os

logger = logging.getLogger("ledger.publisher")

TOPIC_ENV = "PUBSUB_TOPIC"


class LogTransport:
    """Local transport. Writes the event to the structured log.

    Used when no topic is configured, so local runs and tests exercise the same
    relay path without needing cloud credentials.
    """

    name = "log"

    def publish(self, event_id: str, event_type: str, payload: str) -> str:
        logger.info(
            "Event published to log transport",
            extra={"event_type": event_type, "event_id": event_id},
        )
        return f"log:{event_id}"


class PubSubTransport:
    name = "pubsub"

    def __init__(self, topic: str):
        from google.cloud import pubsub_v1

        self._client = pubsub_v1.PublisherClient()
        self._topic = topic

    def publish(self, event_id: str, event_type: str, payload: str) -> str:
        future = self._client.publish(
            self._topic,
            payload.encode("utf-8"),
            event_id=event_id,
            event_type=event_type,
        )
        return future.result(timeout=30)


_transport = None


def get_transport():
    global _transport
    if _transport is None:
        topic = os.getenv(TOPIC_ENV)
        _transport = PubSubTransport(topic) if topic else LogTransport()
        logger.info(f"Outbox transport: {_transport.name}")
    return _transport


def reset_transport() -> None:
    global _transport
    _transport = None
