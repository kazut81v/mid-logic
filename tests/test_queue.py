"""
Task 7-3: Engine-1 → Engine-2 Message Broker Tests
Covers: normal enqueue/dequeue, DLQ rejection, latency tracking, timeout.
"""

import asyncio
import pytest
from schemas.queue import MessageBroker


class TestMessageBroker:
    @pytest.fixture
    def broker(self):
        return MessageBroker(maxsize=100)

    @pytest.mark.asyncio
    async def test_enqueue_and_dequeue(self, broker):
        payload = {"article_id": "a-1", "title": "Test", "body_md": "Body", "source_id": "s-1", "reliability_category": "official", "published_at": 100, "fetched_at": 200, "url": "http://x.com", "content_hash": "h", "metadata": {}}
        result = await broker.enqueue(payload, "NormalizedArticle", "trace-1", "span-1")
        assert result is True
        assert broker.depth == 1
        
        data = await broker.dequeue(timeout=0.5)
        assert data is not None
        assert data[1]["msg_type"] == "NormalizedArticle"
        assert data[1]["payload"]["article_id"] == "a-1"

    @pytest.mark.asyncio
    async def test_enqueue_rejects_invalid_payload(self, broker):
        # Missing required 'article_id' field
        payload = {"title": "Invalid", "body_md": "Body", "source_id": "s-1", "reliability_category": "official", "published_at": 100, "fetched_at": 200, "url": "http://x.com", "content_hash": "h", "metadata": {}}
        result = await broker.enqueue(payload, "NormalizedArticle", "trace-2", "span-2")
        assert result is False
        assert broker.stats["rejected_dlq"] == 1

    @pytest.mark.asyncio
    async def test_enqueue_rejects_unknown_msg_type(self, broker):
        payload = {"some": "data"}
        result = await broker.enqueue(payload, "UnknownType", "trace-3", "span-3")
        assert result is False
        assert broker.stats["rejected_dlq"] == 1

    @pytest.mark.asyncio
    async def test_dequeue_timeout(self, broker):
        data = await broker.dequeue(timeout=0.1)
        assert data is None

    @pytest.mark.asyncio
    async def test_latency_tracking(self, broker):
        payload = {"article_id": "a-1", "title": "Test", "body_md": "Body", "source_id": "s-1", "reliability_category": "official", "published_at": 100, "fetched_at": 200, "url": "http://x.com", "content_hash": "h", "metadata": {}}
        await broker.enqueue(payload, "NormalizedArticle", "trace-4", "span-4")
        await broker.dequeue(timeout=0.5)
        stats = broker.get_stats()
        assert stats["enqueued"] == 1
        assert stats["dequeued"] == 1
        assert stats["avg_latency_ms"] > 0.0  # Should be positive ms

    @pytest.mark.asyncio
    async def test_queue_depth(self, broker):
        payload = {"article_id": "a-1", "title": "Test", "body_md": "Body", "source_id": "s-1", "reliability_category": "official", "published_at": 100, "fetched_at": 200, "url": "http://x.com", "content_hash": "h", "metadata": {}}
        assert broker.depth == 0
        await broker.enqueue(payload, "NormalizedArticle", "trace-5", "span-5")
        assert broker.depth == 1
        await broker.dequeue(timeout=0.5)
        assert broker.depth == 0
