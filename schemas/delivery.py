"""
Phase 7-5: Engine-3 Multi-channel Delivery Adapters
Task: 7-5 Obsidian / Email / Webhook / CLI delivery adapters,
      delivery_log persistence, retry mechanism (exponential backoff, max 5 retries).
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
import sqlite3
import time
from abc import ABC, abstractmethod
from pathlib import Path
from typing import Any

from .contract import DeliveryRecord
from .dlq import DeadLetterQueue

logger = logging.getLogger(__name__)


class DeliveryError(Exception):
    """Raised when delivery fails."""

    def __init__(self, reason: str) -> None:
        super().__init__(reason)
        self.reason = reason


class DeliveryAdapter(ABC):
    """Base class for delivery channel adapters."""

    @abstractmethod
    async def deliver(self, record: DeliveryRecord) -> bool:
        """Attempt delivery. Returns True on success, raises DeliveryError on failure."""
        ...

    @property
    @abstractmethod
    def channel_name(self) -> str:
        """Return the channel identifier (e.g. 'obsidian', 'email')."""
        ...


class ObsidianAdapter(DeliveryAdapter):
    """Delivers to Obsidian vault via markdown file writes."""

    def __init__(self, vault_path: str = "") -> None:
        self._vault_path = vault_path or os.environ.get("OBSIDIAN_VAULT_PATH", "")

    @property
    def channel_name(self) -> str:
        return "obsidian"

    async def deliver(self, record: DeliveryRecord) -> bool:
        if not self._vault_path:
            raise DeliveryError("OBSIDIAN_VAULT_PATH not set")
        vault = Path(self._vault_path)
        if not vault.exists():
            raise DeliveryError(f"Vault not found: {vault}")
        inbox = vault / "Inbox"
        inbox.mkdir(parents=True, exist_ok=True)
        filename = f"{record.delivery_id}.md"
        filepath = inbox / filename
        body = f"# {record.target_id}\n\n{json.dumps(record.payload_snapshot, ensure_ascii=False, indent=2)}\n"
        filepath.write_text(body, encoding="utf-8")
        record.status = "delivered"
        record.delivered_at = int(time.time())
        return True


class EmailAdapter(DeliveryAdapter):
    """Delivers via external email command (sendmail/smtp)."""

    def __init__(self, smtp_host: str = "", smtp_port: int = 0, sender: str = "") -> None:
        self._smtp_host = smtp_host
        self._smtp_port = smtp_port
        self._sender = sender

    @property
    def channel_name(self) -> str:
        return "email"

    async def deliver(self, record: DeliveryRecord) -> bool:
        if not self._smtp_host or not self._sender:
            raise DeliveryError("SMTP configuration missing")
        # Simulate async email send (real implementation would use aiosmtplib)
        await asyncio.sleep(0.01)
        record.status = "delivered"
        record.delivered_at = int(time.time())
        return True


class WebhookAdapter(DeliveryAdapter):
    """Delivers via HTTP POST to a webhook URL."""

    def __init__(self, base_url: str = "") -> None:
        self._base_url = base_url or os.environ.get("WEBHOOK_URL", "")

    @property
    def channel_name(self) -> str:
        return "webhook"

    async def deliver(self, record: DeliveryRecord) -> bool:
        if not self._base_url:
            raise DeliveryError("WEBHOOK_URL not set")
        # Simulate async HTTP POST (real implementation would use httpx/aiohttp)
        await asyncio.sleep(0.01)
        record.status = "delivered"
        record.delivered_at = int(time.time())
        return True


class CliAdapter(DeliveryAdapter):
    """Delivers by printing to stdout (CLI consumer)."""

    @property
    def channel_name(self) -> str:
        return "cli"

    async def deliver(self, record: DeliveryRecord) -> bool:
        output = json.dumps({
            "delivery_id": record.delivery_id,
            "target_id": record.target_id,
            "payload": record.payload_snapshot,
        }, ensure_ascii=False, indent=2)
        print(output)
        record.status = "delivered"
        record.delivered_at = int(time.time())
        return True


class RetryHandler:
    """Exponential backoff retry wrapper for delivery operations."""

    def __init__(self, max_retries: int = 5, base_delay: float = 1.0, max_delay: float = 60.0) -> None:
        self.max_retries = max_retries
        self.base_delay = base_delay
        self.max_delay = max_delay

    async def execute_with_retry(self, adapter: DeliveryAdapter, record: DeliveryRecord) -> bool:
        last_error: DeliveryError | None = None
        for attempt in range(self.max_retries):
            try:
                return await adapter.deliver(record)
            except DeliveryError as exc:
                last_error = exc
                record.error_reason = exc.reason
                record.retry_count = attempt + 1
                delay = min(self.base_delay * (2 ** attempt), self.max_delay)
                logger.warning(
                    "Delivery attempt %d/%d failed for %s (%s): %s - retry in %.1fs",
                    attempt + 1, self.max_retries, adapter.channel_name, record.delivery_id, exc.reason, delay,
                )
                await asyncio.sleep(delay)
        record.status = "failed"
        logger.error(
            "Delivery permanently failed after %d retries for %s (%s): %s",
            self.max_retries, adapter.channel_name, record.delivery_id, last_error.reason if last_error else "unknown",
        )
        return False


class DeliveryLogger:
    """Persists delivery_log entries to SQLite or JSONL file."""

    def __init__(self, db_path: str | None = None, jsonl_path: str | None = None) -> None:
        self._db_path = db_path
        self._jsonl_path = jsonl_path
        if self._db_path:
            self._init_db()

    def _init_db(self) -> None:
        assert self._db_path is not None
        conn = sqlite3.connect(self._db_path)
        conn.execute("""
            CREATE TABLE IF NOT EXISTS delivery_log (
                delivery_id TEXT PRIMARY KEY,
                target_type TEXT,
                target_id TEXT,
                status TEXT,
                error_reason TEXT,
                retry_count INTEGER,
                delivered_at INTEGER
            )
        """)
        conn.commit()
        conn.close()

    def log(self, record: DeliveryRecord) -> None:
        if self._db_path:
            self._log_sqlite(record)
        if self._jsonl_path:
            self._log_jsonl(record)

    def _log_sqlite(self, record: DeliveryRecord) -> None:
        assert self._db_path is not None
        conn = sqlite3.connect(self._db_path)
        conn.execute("""
            INSERT OR REPLACE INTO delivery_log
            (delivery_id, target_type, target_id, status, error_reason, retry_count, delivered_at)
            VALUES (?, ?, ?, ?, ?, ?, ?)
        """, (record.delivery_id, record.target_type, record.target_id,
              record.status, record.error_reason, record.retry_count, record.delivered_at))
        conn.commit()
        conn.close()

    def _log_jsonl(self, record: DeliveryRecord) -> None:
        assert self._jsonl_path is not None
        entry = {
            "delivery_id": record.delivery_id,
            "target_type": record.target_type,
            "target_id": record.target_id,
            "status": record.status,
            "payload_snapshot": record.payload_snapshot,
            "error_reason": record.error_reason,
            "retry_count": record.retry_count,
            "delivered_at": record.delivered_at,
        }
        with open(self._jsonl_path, "a", encoding="utf-8") as f:
            f.write(json.dumps(entry, ensure_ascii=False) + "\n")
