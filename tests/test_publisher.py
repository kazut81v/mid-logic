"""
Tests for the Engine-3 Publisher core (T2).

Covers: idempotency key generation, envelope verification failure -> DLQ routing,
channel dispatch, exponential backoff retry (max 3), DLQ integration.
"""

import asyncio
import pytest

from schemas.contract import DeliveryRecord
from schemas.delivery import DeliveryAdapter, DeliveryError
from schemas.dlq import DeadLetterQueue
from schemas.publisher import Publisher
from schemas.verify import verify_envelope


class FailingAdapter(DeliveryAdapter):
    """Always fails delivery."""

    @property
    def channel_name(self) -> str:
        return "failing"

    async def deliver(self, record: DeliveryRecord) -> bool:
        raise DeliveryError("Connection timeout")


class SuccessAdapter(DeliveryAdapter):
    """Always succeeds delivery."""

    @property
    def channel_name(self) -> str:
        return "success"

    async def deliver(self, record: DeliveryRecord) -> bool:
        record.status = "delivered"
        record.delivered_at = int(asyncio.get_event_loop().time())
        return True


class EventuallySuccessAdapter(DeliveryAdapter):
    """Fails 'fail_count' times, then succeeds."""

    def __init__(self, fail_count: int = 2) -> None:
        self.fail_count = fail_count
        self.call_count = 0

    @property
    def channel_name(self) -> str:
        return "eventual"

    async def deliver(self, record: DeliveryRecord) -> bool:
        self.call_count += 1
        if self.call_count <= self.fail_count:
            raise DeliveryError("Transient error")
        record.status = "delivered"
        record.delivered_at = int(asyncio.get_event_loop().time())
        return True


class TestPublisherIdempotency:
    def test_generate_idempotency_key(self):
        publisher = Publisher(channels=[])
        key1 = publisher.generate_idempotency_key({"id": 1, "name": "test"})
        key2 = publisher.generate_idempotency_key({"id": 1, "name": "test"})
        assert key1 == key2
        assert len(key1) == 64  # SHA-256 hex digest

    def test_is_duplicate(self):
        publisher = Publisher(channels=[])
        key = publisher.generate_idempotency_key({"id": 1})
        assert not publisher.is_duplicate(key)
        publisher.mark_processed(key)
        assert publisher.is_duplicate(key)

    def test_mark_processed(self):
        publisher = Publisher(channels=[])
        publisher.mark_processed("key-1")
        assert publisher.is_duplicate("key-1")


class TestPublisherEnvelopeValidation:
    def test_verify_success(self):
        raw = (
            b'{"spec_version":"v1","msg_type":"NormalizedArticle","trace_id":"trace-1",'
            b'"span_id":"span-1","timestamp_ns":1234567890,'
            b'"payload":{"article_id":"a-1","source_id":"s-1","reliability_category":"official",'
            b'"title":"Test","body_md":"Body","published_at":100,"fetched_at":200,"url":"http://x.com",'
            b'"content_hash":"hash","metadata":{}}}'
        )
        ok, err, validated = verify_envelope(raw)
        assert ok is True
        assert err is None
        assert validated is not None
        assert validated["msg_type"] == "NormalizedArticle"
        assert validated["trace_id"] == "trace-1"

    def test_verify_failure_unknown_msg_type(self):
        raw = (
            b'{"spec_version":"v1","msg_type":"UnknownType","trace_id":"trace-1",'
            b'"span_id":"span-1","timestamp_ns":1234567890,'
            b'"payload":{}}'
        )
        ok, err, validated = verify_envelope(raw)
        assert ok is False
        assert err is not None
        assert validated is None

    def test_verify_failure_missing_payload_field(self):
        # Envelope with missing required fields (no msg_type, no trace_id)
        raw = b'{"spec_version":"v1"}'
        ok, err, validated = verify_envelope(raw)
        assert ok is False


class TestPublisherPublish:
    @pytest.fixture
    def dlq(self):
        return DeadLetterQueue()

    @pytest.fixture
    def envelope_raw(self):
        return (
            b'{"spec_version":"v1","msg_type":"NormalizedArticle","trace_id":"trace-1",'
            b'"span_id":"span-1","timestamp_ns":1234567890,'
            b'"payload":{"article_id":"a-1","source_id":"s-1","reliability_category":"official",'
            b'"title":"Test","body_md":"Body","published_at":100,"fetched_at":200,"url":"http://x.com",'
            b'"content_hash":"hash","metadata":{}}}'
        )

    @pytest.fixture
    def publisher(self, dlq):
        return Publisher(channels=[SuccessAdapter()], dlq=dlq)

    @pytest.mark.asyncio
    async def test_publish_success(self, publisher, envelope_raw):
        result = await publisher.publish(envelope_raw)
        assert result is True
        assert publisher.is_duplicate(publisher.generate_idempotency_key(envelope_raw)) is True

    @pytest.mark.asyncio
    async def test_publish_duplicate(self, publisher, envelope_raw):
        await publisher.publish(envelope_raw)
        result = await publisher.publish(envelope_raw)
        assert result is False  # duplicate

    @pytest.mark.asyncio
    async def test_publish_verification_failure(self, publisher, dlq):
        # Malformed envelope (missing msg_type) -> DLQ routing
        raw = b'{"spec_version":"v1"}'
        result = await publisher.publish(raw)
        assert result is False
        # DLQ should have recorded the message
        assert dlq is not None
        assert len(dlq.get_all()) == 1


class TestPublisherDlqIntegration:
    @pytest.fixture
    def dlq(self):
        return DeadLetterQueue()

    @pytest.fixture
    def publisher(self, dlq):
        return Publisher(channels=[FailingAdapter()], dlq=dlq, max_retries=3)

    @pytest.mark.asyncio
    async def test_publish_verification_failure_routes_to_dlq(self, publisher):
        raw = b'{"spec_version":"v1"}'
        result = await publisher.publish(raw)
        assert result is False
        assert len(publisher.dlq.get_all()) == 1
        entry = publisher.dlq.get_all()[0]
        assert entry["msg_type"] == "unknown"
        assert "validation" in entry["error_reason"].lower()

    @pytest.mark.asyncio
    async def test_publish_channel_failure_routes_to_dlq(self, publisher):
        result = await publisher.publish(
            b'{"spec_version":"v1","msg_type":"NormalizedArticle","trace_id":"trace-1",'
            b'"span_id":"span-1","timestamp_ns":1234567890,'
            b'"payload":{"article_id":"a-1","source_id":"s-1","reliability_category":"official",'
            b'"title":"Test","body_md":"Body","published_at":100,"fetched_at":200,"url":"http://x.com",'
            b'"content_hash":"hash","metadata":{}}}'
        )
        assert result is False
        assert len(publisher.dlq.get_all()) == 1
        entry = publisher.dlq.get_all()[0]
        assert entry["msg_type"] == "NormalizedArticle"
        assert entry["trace_id"] == "trace-1"
        assert "delivery" in entry["error_reason"].lower()


class TestPublisherExponentialBackoff:
    @pytest.fixture
    def publisher_eventual_success(self):
        return Publisher(channels=[EventuallySuccessAdapter(fail_count=2)], max_retries=3)

    @pytest.fixture
    def publisher_permanent_failure(self):
        return Publisher(channels=[EventuallySuccessAdapter(fail_count=3)], max_retries=3)

    @pytest.mark.asyncio
    async def test_publish_with_retry_eventual_success(self, publisher_eventual_success):
        envelope_raw = (
            b'{"spec_version":"v1","msg_type":"NormalizedArticle","trace_id":"trace-1",'
            b'"span_id":"span-1","timestamp_ns":1234567890,'
            b'"payload":{"article_id":"a-1","source_id":"s-1","reliability_category":"official",'
            b'"title":"Test","body_md":"Body","published_at":100,"fetched_at":200,"url":"http://x.com",'
            b'"content_hash":"hash","metadata":{}}}'
        )
        result = await publisher_eventual_success.publish(envelope_raw)
        assert result is True
        assert publisher_eventual_success._retry_handler.max_retries == 3

    @pytest.mark.asyncio
    async def test_publish_with_retry_permanent_failure(self, publisher_permanent_failure):
        envelope_raw = (
            b'{"spec_version":"v1","msg_type":"NormalizedArticle","trace_id":"trace-2",'
            b'"span_id":"span-2","timestamp_ns":1234567891,'
            b'"payload":{"article_id":"a-2","source_id":"s-2","reliability_category":"official",'
            b'"title":"Test","body_md":"Body","published_at":100,"fetched_at":200,"url":"http://x.com",'
            b'"content_hash":"hash","metadata":{}}}'
        )
        result = await publisher_permanent_failure.publish(envelope_raw)
        assert result is False


class TestPublisherChannelDispatch:
    @pytest.fixture
    def publisher(self):
        return Publisher(channels=[SuccessAdapter(), SuccessAdapter()])

    @pytest.mark.asyncio
    async def test_publish_multiple_channels(self, publisher):
        envelope_raw = (
            b'{"spec_version":"v1","msg_type":"NormalizedArticle","trace_id":"trace-1",'
            b'"span_id":"span-1","timestamp_ns":1234567890,'
            b'"payload":{"article_id":"a-1","source_id":"s-1","reliability_category":"official",'
            b'"title":"Test","body_md":"Body","published_at":100,"fetched_at":200,"url":"http://x.com",'
            b'"content_hash":"hash","metadata":{}}}'
        )
        result = await publisher.publish(envelope_raw)
        assert result is True
