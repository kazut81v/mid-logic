"""
Phase 7-5: Tests for delivery adapters, retry handler, and delivery logger.
"""

import asyncio
import json
import os
import tempfile
from pathlib import Path

import msgspec
import pytest

from schemas.contract import DeliveryRecord
from schemas.delivery import (
    CliAdapter,
    DeliveryError,
    DeliveryLogger,
    EmailAdapter,
    ObsidianAdapter,
    RetryHandler,
    WebhookAdapter,
)


@pytest.fixture
def sample_delivery_record():
    return DeliveryRecord(
        delivery_id="d-1",
        target_type="obsidian",
        target_id="test-topic",
        payload_snapshot={"topic": "Test Topic", "summary": "Test summary"},
        status="pending",
    )


@pytest.fixture
def tmp_obsidian_vault(tmp_path):
    vault = tmp_path / "vault" / "Inbox"
    vault.mkdir(parents=True)
    return str(vault.parent)


class TestObsidianAdapter:
    def test_deliver_success(self, sample_delivery_record, tmp_obsidian_vault):
        adapter = ObsidianAdapter(vault_path=tmp_obsidian_vault)
        result = asyncio.run(adapter.deliver(sample_delivery_record))
        assert result is True
        assert sample_delivery_record.status == "delivered"
        assert sample_delivery_record.delivered_at > 0
        # Verify file was created
        inbox = Path(tmp_obsidian_vault) / "Inbox"
        files = list(inbox.glob("*.md"))
        assert len(files) == 1
        assert "d-1.md" in files[0].name

    def test_deliver_no_vault(self, sample_delivery_record):
        adapter = ObsidianAdapter(vault_path="/nonexistent/path")
        with pytest.raises(DeliveryError, match="Vault not found"):
            asyncio.run(adapter.deliver(sample_delivery_record))

    def test_deliver_no_path_set(self, sample_delivery_record, monkeypatch):
        monkeypatch.delenv("OBSIDIAN_VAULT_PATH", raising=False)
        adapter = ObsidianAdapter()
        with pytest.raises(DeliveryError, match="OBSIDIAN_VAULT_PATH not set"):
            asyncio.run(adapter.deliver(sample_delivery_record))

    def test_channel_name(self, sample_delivery_record):
        adapter = ObsidianAdapter(vault_path="/tmp")
        assert adapter.channel_name == "obsidian"


class TestEmailAdapter:
    def test_deliver_success(self, sample_delivery_record):
        adapter = EmailAdapter(smtp_host="localhost", smtp_port=587, sender="test@example.com")
        result = asyncio.run(adapter.deliver(sample_delivery_record))
        assert result is True
        assert sample_delivery_record.status == "delivered"

    def test_deliver_missing_config(self, sample_delivery_record):
        adapter = EmailAdapter()
        with pytest.raises(DeliveryError, match="SMTP configuration missing"):
            asyncio.run(adapter.deliver(sample_delivery_record))

    def test_channel_name(self, sample_delivery_record):
        adapter = EmailAdapter(smtp_host="localhost")
        assert adapter.channel_name == "email"


class TestWebhookAdapter:
    def test_deliver_success(self, sample_delivery_record):
        adapter = WebhookAdapter(base_url="http://localhost:8080/hook")
        result = asyncio.run(adapter.deliver(sample_delivery_record))
        assert result is True
        assert sample_delivery_record.status == "delivered"

    def test_deliver_no_url(self, sample_delivery_record):
        adapter = WebhookAdapter()
        with pytest.raises(DeliveryError, match="WEBHOOK_URL not set"):
            asyncio.run(adapter.deliver(sample_delivery_record))

    def test_channel_name(self, sample_delivery_record):
        adapter = WebhookAdapter(base_url="http://localhost/hook")
        assert adapter.channel_name == "webhook"


class TestCliAdapter:
    def test_deliver_success(self, sample_delivery_record, capsys):
        adapter = CliAdapter()
        result = asyncio.run(adapter.deliver(sample_delivery_record))
        assert result is True
        assert sample_delivery_record.status == "delivered"
        captured = capsys.readouterr()
        output = json.loads(captured.out)
        assert output["delivery_id"] == "d-1"
        assert output["payload"]["topic"] == "Test Topic"

    def test_channel_name(self, sample_delivery_record):
        adapter = CliAdapter()
        assert adapter.channel_name == "cli"


class TestRetryHandler:
    @pytest.fixture
    def failing_adapter(self):
        class AlwaysFailsAdapter(ObsidianAdapter):
            def __init__(self):
                pass

            @property
            def channel_name(self):
                return "failing"

            async def deliver(self, record):
                raise DeliveryError("Connection timeout")

        return AlwaysFailsAdapter()

    @pytest.fixture
    def success_after_2_adapter(self):
        class SuccessAfterNAdapter(ObsidianAdapter):
            def __init__(self):
                self._call_count = 0

            @property
            def channel_name(self):
                return "eventual"

            async def deliver(self, record):
                self._call_count += 1
                if self._call_count < 2:
                    raise DeliveryError("Transient error")
                record.status = "delivered"
                record.delivered_at = int(asyncio.get_event_loop().time())
                return True

        return SuccessAfterNAdapter()

    def test_retry_all_fail(self, sample_delivery_record, failing_adapter):
        handler = RetryHandler(max_retries=3, base_delay=0.001)
        result = asyncio.run(handler.execute_with_retry(failing_adapter, sample_delivery_record))
        assert result is False
        assert sample_delivery_record.status == "failed"
        assert sample_delivery_record.retry_count == 3

    def test_retry_eventual_success(self, sample_delivery_record, success_after_2_adapter):
        handler = RetryHandler(max_retries=3, base_delay=0.001)
        result = asyncio.run(handler.execute_with_retry(success_after_2_adapter, sample_delivery_record))
        assert result is True
        assert sample_delivery_record.status == "delivered"
        assert sample_delivery_record.retry_count == 1


class TestDeliveryLogger:
    def test_log_sqlite(self, sample_delivery_record, tmp_path):
        db_path = str(tmp_path / "delivery.db")
        logger = DeliveryLogger(db_path=db_path)
        sample_delivery_record.status = "delivered"
        sample_delivery_record.delivered_at = 1234567890
        logger.log(sample_delivery_record)

        import sqlite3
        conn = sqlite3.connect(db_path)
        row = conn.execute("SELECT * FROM delivery_log WHERE delivery_id=?", (sample_delivery_record.delivery_id,)).fetchone()
        conn.close()
        assert row is not None
        assert row[0] == "d-1"
        assert row[3] == "delivered"

    def test_log_jsonl(self, sample_delivery_record, tmp_path):
        jsonl_path = str(tmp_path / "delivery.jsonl")
        logger = DeliveryLogger(jsonl_path=jsonl_path)
        sample_delivery_record.status = "delivered"
        sample_delivery_record.delivered_at = 1234567890
        logger.log(sample_delivery_record)

        with open(jsonl_path, "r", encoding="utf-8") as f:
            lines = f.readlines()
        assert len(lines) == 1
        entry = json.loads(lines[0])
        assert entry["delivery_id"] == "d-1"
        assert entry["status"] == "delivered"

    def test_log_both_sqlite_and_jsonl(self, sample_delivery_record, tmp_path):
        db_path = str(tmp_path / "delivery.db")
        jsonl_path = str(tmp_path / "delivery.jsonl")
        logger = DeliveryLogger(db_path=db_path, jsonl_path=jsonl_path)
        sample_delivery_record.status = "delivered"
        logger.log(sample_delivery_record)

        import sqlite3
        conn = sqlite3.connect(db_path)
        row = conn.execute("SELECT status FROM delivery_log WHERE delivery_id=?", (sample_delivery_record.delivery_id,)).fetchone()
        conn.close()
        assert row is not None
        assert row[0] == "delivered"

        with open(jsonl_path, "r", encoding="utf-8") as f:
            entry = json.loads(f.readline())
        assert entry["status"] == "delivered"
