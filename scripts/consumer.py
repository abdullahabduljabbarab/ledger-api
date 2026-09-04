"""Downstream consumer for transaction events.

Reads from the Pub/Sub subscription the outbox relay publishes to. The relay is
at-least-once, so the same event can arrive more than once and the consumer
deduplicates on the event_id attribute before acting on a message.

    export PUBSUB_SUBSCRIPTION=projects/<project>/subscriptions/transaction-events-sub
    python scripts/consumer.py

The dedupe set here is in memory, which is enough to demonstrate the contract.
A production consumer would keep processed event ids in its own datastore so
deduplication survives a restart.
"""

import json
import os
import signal
import sys
from threading import Event

from google.cloud import pubsub_v1

SUBSCRIPTION = os.getenv("PUBSUB_SUBSCRIPTION")


class Deduplicator:
    """Tracks processed event ids so a redelivered event is a no-op.

    The relay is at-least-once, so this is what makes the consumer safe to run
    against real Pub/Sub. Kept as a pure object so the contract can be tested
    without a live subscription.
    """

    def __init__(self):
        self._seen = set()

    def is_duplicate(self, event_id: str) -> bool:
        return event_id in self._seen

    def mark(self, event_id: str) -> None:
        self._seen.add(event_id)

    def __len__(self) -> int:
        return len(self._seen)


dedup = Deduplicator()
shutdown = Event()

totals = {"deposit": 0, "withdrawal": 0, "transfer": 0}


def handle(message):
    event_id = message.attributes.get("event_id")
    event_type = message.attributes.get("event_type", "unknown")

    if dedup.is_duplicate(event_id):
        print(f"duplicate  {event_type}  event_id={event_id}  (already processed)")
        message.ack()
        return

    try:
        payload = json.loads(message.data.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as e:
        # Do not ack: let the subscription retry, then dead-letter it.
        print(f"malformed message, leaving unacked: {e}")
        message.nack()
        return

    kind = payload.get("type")
    if kind in totals:
        totals[kind] += 1

    dedup.mark(event_id)
    print(
        f"received   {event_type}  amount={payload.get('amount')}  "
        f"txn={payload.get('transaction_id')}"
    )
    print(f"           running totals: {totals}")
    message.ack()


def main():
    if not SUBSCRIPTION:
        sys.exit("PUBSUB_SUBSCRIPTION is not set")

    subscriber = pubsub_v1.SubscriberClient()
    future = subscriber.subscribe(SUBSCRIPTION, callback=handle)
    print(f"listening on {SUBSCRIPTION}, press Ctrl+C to stop")

    signal.signal(signal.SIGINT, lambda *_: shutdown.set())
    shutdown.wait()

    future.cancel()
    future.result(timeout=30)
    print(f"\nstopped. processed {len(dedup)} unique events: {totals}")


if __name__ == "__main__":
    main()
