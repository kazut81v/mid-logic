"""
Engine-3 Publisher: async delivery core with channel abstraction and idempotency.

Combines channel abstraction (DeliveryAdapter), idempotency key generation,
exponential backoff retry (max 3 retries), and DLQ integration into a single
async delivery kernel. Compatible with existing DLQ integration
(verify_envelope failure -> DLQ record) and consistent with T1/T3/T4
deliverables (DeliveryRecord, DeliveryAdapter, DeliveryManager).
"""

from __future__ import annotations

import hashlib
import logging
from typing import Any

from .contract import DeliveryRecord
from .delivery import DeliveryAdapter, RetryHandler
from .dlq import DeadLetterQueue
from .verify import verify_envelope

logger = logging.getLogger(__name__)


class Publisher:
    """Engine-3 async delivery publisher core.

    Responsibilities:
    - async asynchronous delivery kernel (publishes to multiple channels)
    - channel abstraction (uses DeliveryAdapter interface)
    - idempotency_key generation (SHA-256 of payload)
    - exponential backoff retry (max 3 retries by default)
    - DLQ integration (verify_envelope failure -> DLQ record)
    """

    def __init__(
        self,
        channels: list[DeliveryAdapter],
        dlq: DeadLetterQueue | None = None,
        max_retries: int = 3,
        base_delay: float = 1.0,
        max_delay: float = 60.0,
        use_idempotency: bool = True,
    ) -> None:
        self.channels = channels or []
        self.dlq = dlq
        self.max_retries = max_retries
        self.base_delay = base_delay
        self.max_delay = max_delay
        self.use_idempotency = use_idempotency
        self._processed_keys: set[str] = set()
        self._retry_handler = RetryHandler(
            max_retries=max_retries, base_delay=base_delay, max_delay=max_delay
        )
        self._logger = logging.getLogger(__name__)

    # ------------------------------------------------------------------
    # Idempotency
    # ------------------------------------------------------------------

    def generate_idempotency_key(self, data: dict | str | bytes | None) -> str:
        """Generate a SHA-256 idempotency key from payload data."""
        if data is None:
            data = ""
        return hashlib.sha256(str(data).encode("utf-8")).hexdigest()

    def is_duplicate(self, key: str) -> bool:
        """Return True if the key has already been processed."""
        return key in self._processed_keys

    def mark_processed(self, key: str) -> None:
        """Mark a key as processed."""
        self._processed_keys.add(key)

    # ------------------------------------------------------------------
    # Main entry point
    # ------------------------------------------------------------------

    async def publish(self, envelope_raw: bytes) -> bool:
        """Verify envelope, generate idempotency key, dispatch to channels.

        Returns True on success, False on verification failure or duplicate.
        """
        ok, err, validated = verify_envelope(envelope_raw)
        if not ok:
            self._route_to_dlq(validated, err or "verification failed")
            self._logger.warning(f"Envelope verification failed: {err}")
            return False

        idempotency_key = self.generate_idempotency_key(envelope_raw)
        if self.use_idempotency and self.is_duplicate(idempotency_key):
            self._logger.warning(f"Duplicate message detected: {idempotency_key}")
            return False
        if self.use_idempotency:
            self.mark_processed(idempotency_key)

        record = self._to_delivery_record(validated)
        return await self._dispatch(record)

    # ------------------------------------------------------------------
    # DLQ integration
    # ------------------------------------------------------------------

    def _route_to_dlq(self, validated: dict | None, error_reason: str) -> None:
        """Route a failed message to the DLQ."""
        if self.dlq is None:
            return
        if validated:
            self.dlq.record(
                msg_type=validated.get("msg_type", "unknown"),
                payload=validated.get("payload", {}),
                error_reason=error_reason,
                trace_id=validated.get("trace_id", "unknown"),
            )
        else:
            self.dlq.record(
                msg_type="unknown",
                payload={},
                error_reason=error_reason,
                trace_id="unknown",
            )

    # ------------------------------------------------------------------
    # DeliveryRecord conversion
    # ------------------------------------------------------------------

    def _to_delivery_record(self, validated: dict | None) -> DeliveryRecord:
        """Convert a validated envelope dict to a DeliveryRecord."""
        if validated is None:
            validated = {}
        return DeliveryRecord(
            delivery_id=validated.get("trace_id", ""),
            target_type=validated.get("msg_type", "unknown"),
            target_id=validated.get("span_id", ""),
            status="pending",
            payload_snapshot=validated.get("payload", {}),
            delivered_at=0,
            error_reason="",
            retry_count=0,
        )

    # ------------------------------------------------------------------
    # Channel dispatch
    # ------------------------------------------------------------------

    async def _dispatch(self, record: DeliveryRecord) -> bool:
        """Dispatch a DeliveryRecord to all configured channels.

        Uses exponential backoff retry (RetryHandler) for each channel.
        Routes to DLQ if any channel fails after all retries.

        Returns True if all channels succeeded, False otherwise.
        """
        all_ok = True
        for adapter in self.channels:
            channel_name = adapter.channel_name
            try:
                ok = await self._retry_handler.execute_with_retry(adapter, record)
                if ok:
                    self._logger.info(
                        "Channel '%s' delivered: %s", channel_name, record.delivery_id
                    )
                else:
                    all_ok = False
                    self._logger.error(
                        "Channel '%s' delivery failed after retries: %s",
                        channel_name,
                        record.delivery_id,
                    )
            except Exception as exc:  # DeliveryError or unexpected
                all_ok = False
                self._logger.error(
                    "Channel '%s' raised exception for %s: %s",
                    channel_name,
                    record.delivery_id,
                    exc,
                )

        if not all_ok and self.dlq is not None:
            self._route_to_dlq(
                {
                    "msg_type": record.target_type,
                    "payload": record.payload_snapshot,
                    "trace_id": record.delivery_id,
                },
                "Channel delivery failed after retries",
            )

        return all_ok
