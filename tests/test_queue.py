"""
Task 7-3: Engine-1 → Engine-2 Message Broker Tests
Covers: normal enqueue/dequeue, DLQ rejection, latency tracking, timeout.
"""

import pytest
import asyncio
import msgspec
from schemas.contract import Envelope
from schemas.queue import MessageBroker


@pytest.fixture
def broker():
    return MessageBroker(maxsize=1000)


@pytest.mark.asyncio
async def test_enqueue_and_dequeue(broker):
    payload = {"article_id": "a-1", "title": "Test", "body_md": "Body",
               "source_id": "s-1", "reliability_category": "official",
               "published_at": 100, "fetched_at": 200,
               "url": "http://x.com", "content_hash": "h", "metadata": {}}
    ok = await broker.enqueue(payload, "NormalizedArticle", "trace-1", "span-1")
    assert ok is True
    result = await asyncio.wait_for(broker.dequeue(), timeout=1.0)
    assert result is not None
    assert result["article_id"] == "a-1"
    assert broker.get_stats()["enqueued"] == 1
    assert broker.get_stats()["dequeued"] == 1


@pytest.mark.asyncio
async def test_enqueue_rejects_invalid_payload(broker):
    bad = {"missing": "fields"}
    ok = await broker.enqueue(bad, "SynthesisResult", "trace-2", "span-2")
    assert ok is False
    assert broker.get_stats()["rejected_dlq"] == 1
    assert broker.dlq.get_stats()["count"] == 1


@pytest.mark.asyncio
async def test_enqueue_rejects_unknown_msg_type(broker):
    ok = await broker.enqueue({}, "UnknownType", "trace-3", "span-3")
    assert ok is False
    assert broker.get_stats()["rejected_dlq"] == 1


@pytest.mark.asyncio
async def test_dequeue_timeout(broker):
    result = await broker.dequeue(timeout=0.1)
    assert result is None


@pytest.mark.asyncio
async def test_latency_tracking(broker):
    payload = {"article_id": "a-1", "title": "Test", "body_md": "Body",
               "source_id": "s-1", "reliability_category": "official",
               "published_at": 100, "fetched_at": 200,
               "url": "http://x.com", "content_hash": "h", "metadata": {}}
    await broker.enqueue(payload, "NormalizedArticle", "trace-4", "span-4")
    await broker.dequeue(timeout=0.5)
    stats = broker.get_stats()
    assert stats["enqueued"] == 1
    assert stats["dequeued"] == 1
    assert stats["avg_latency_ms"] >= 0.0  # Should be non-negative ms


@pytest.mark.asyncio
async def test_queue_depth(broker):
    payload = {"article_id": "a-1", "title": "Test", "body_md": "Body",
               "source_id": "s-1", "reliability_category": "official",
               "published_at": 100, "fetched_at": 200,
               "url": "http://x.com", "content_hash": "h", "metadata": {}}
    for i in range(5):
        await broker.enqueue(payload, "NormalizedArticle", f"trace-{i}", f"span-{i}")
    assert broker.get_stats()["enqueued"] == 5
    assert broker.get_stats()["dequeued"] == 0
    depth = broker._queue.qsize()
    assert depth == 5
