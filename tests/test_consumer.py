import os
import sys

sys.path.insert(
    0, os.path.join(os.path.dirname(__file__), "..", "scripts")
)

from consumer import Deduplicator  # noqa: E402


def test_first_delivery_is_not_a_duplicate():
    d = Deduplicator()
    assert d.is_duplicate("evt-1") is False


def test_redelivery_is_a_duplicate():
    d = Deduplicator()
    d.mark("evt-1")
    assert d.is_duplicate("evt-1") is True


def test_distinct_events_are_independent():
    d = Deduplicator()
    d.mark("evt-1")
    assert d.is_duplicate("evt-2") is False
    d.mark("evt-2")
    assert len(d) == 2


def test_marking_twice_counts_once():
    d = Deduplicator()
    d.mark("evt-1")
    d.mark("evt-1")
    assert len(d) == 1
