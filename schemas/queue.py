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
    def __init__(self, maxsize: int = 1000, dlq: DeadLetterQueue | None = None):
        self._queue: asyncio.Queue = asyncio.Queue(maxsize=maxsize)
        self._dlq = dlq if dlq is not None else DeadLetterQueue()
        self._stats = {
            "enqueued": 0,
            "dequeued": 0,
            "rejected_dlq": 0,
            "avg_latency_ms": 0.0
        }
        self._latency_sum = 0.0

    async def enqueue(self, payload: dict, msg_type: str, trace_id: str, span_id: str) -> bool:
        """
        Creates envelope, verifies, and enqueues.
        Returns True on success, False if validation fails (routed to DLQ).
        """
        env = Envelope(
            spec_version="v1",
            msg_type=msg_type,
            trace_id=trace_id,
            span_id=span_id,
            timestamp_ns=int(time.time_ns()),
            payload=payload
        )
        
        # Serialize and verify before enqueueing to fail fast
        raw = msgspec.json.encode(env)
        ok, err, validated = verify_envelope(raw)
        if not ok:
            self._stats["rejected_dlq"] += 1
            # Record to DLQ (protocol: invalid envelopes must be persisted)
            self._dlq.record(msg_type, payload, str(err), trace_id)
            return False
        
        await self._queue.put((time.time_ns(), validated))
        self._stats["enqueued"] += 1
        return True

    async def dequeue(self, timeout: float = 1.0) -> tuple[int, dict] | None:
        """
        Retrieves next message from queue.
        Returns (enqueue_timestamp_ns, message_dict) or None on timeout.
        """
        try:
            enqueue_ts_ns, msg_dict = await asyncio.wait_for(self._queue.get(), timeout=timeout)
            dequeue_ts_ns = time.time_ns()
            latency_ms = (dequeue_ts_ns - enqueue_ts_ns) / 1_000_000
            
            count = self._stats["dequeued"] + 1
            self._stats["avg_latency_ms"] = (
                (self._stats["avg_latency_ms"] * self._stats["dequeued"] + latency_ms) / count
            )
            self._stats["dequeued"] += 1
            self._queue.task_done()
            return (enqueue_ts_ns, msg_dict)
        except asyncio.TimeoutError:
            return None

    @property
    def stats(self) -> dict:
        return self._stats

    def get_stats(self) -> dict:
        return self._stats.copy()

    @property
    def depth(self) -> int:
        return self._queue.qsize()
