"""
Engine-1 → Engine-2 Message Queue Broker (Task 7-3)
in-proc asyncio.Queue implementation.
"""

import asyncio
import time
import msgspec
from schemas.contract import Envelope
from schemas.verify import verify_envelope
from schemas.dlq import DeadLetterQueue


class MessageBroker:
    def __init__(self, maxsize: int = 1000):
        self._queue: asyncio.Queue = asyncio.Queue(maxsize=maxsize)
        self._dlq = DeadLetterQueue(max_size=10000)
        self._stats = {
            "enqueued": 0,
            "dequeued": 0,
            "rejected_dlq": 0,
            "avg_latency_ms": 0.0
        }
        self._latency_sum = 0.0
        self._latency_count = 0

    async def enqueue(self, payload: dict, msg_type: str, trace_id: str, span_id: str) -> bool:
        # Reject unknown message types
        known_types = {"NormalizedArticle", "SynthesisResult", "DeliveryRecord"}
        if msg_type not in known_types:
            self._stats["rejected_dlq"] += 1
            self._dlq.record(
                msg_type=msg_type,
                payload=payload,
                error_reason=f"unknown msg_type: {msg_type}",
                trace_id=trace_id
            )
            return False
        raw = msgspec.json.encode(Envelope(
            spec_version="v1",
            msg_type=msg_type,
            trace_id=trace_id,
            span_id=span_id,
            timestamp_ns=int(time.time_ns()),
            payload=payload
        ))
        ok, err, validated = verify_envelope(raw)
        if not ok:
            self._stats["rejected_dlq"] += 1
            self._dlq.record(
                msg_type=msg_type,
                payload=payload,
                error_reason=err or "unknown validation error",
                trace_id=trace_id
            )
            return False
        try:
            self._queue.put_nowait((validated, time.time_ns()))
            self._stats["enqueued"] += 1
            return True
        except asyncio.QueueFull:
            self._dlq.record(
                msg_type=msg_type,
                payload=payload,
                error_reason="queue full",
                trace_id=trace_id
            )
            return False

    async def dequeue(self, timeout: float | None = None) -> tuple | None:
        try:
            if timeout is not None:
                validated, enqueue_ts = await asyncio.wait_for(
                    self._queue.get(), timeout=timeout
                )
            else:
                validated, enqueue_ts = await self._queue.get()
            dequeue_ts = time.time_ns()
            latency_ms = (dequeue_ts - enqueue_ts) / 1_000_000
            self._latency_sum += latency_ms
            self._latency_count += 1
            self._stats["avg_latency_ms"] = (
                self._latency_sum / self._latency_count
            )
            self._stats["dequeued"] += 1
            return validated
        except asyncio.TimeoutError:
            return None

    def get_stats(self) -> dict:
        return {**self._stats}

    @property
    def dlq(self) -> DeadLetterQueue:
        return self._dlq
