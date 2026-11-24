"""
Task 7-4: Dead Letter Queue (DLQ) Implementation
Records rejected messages for later inspection or manual replay.
"""

import json
import time
import logging
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional


@dataclass
class DroppedMessage:
    timestamp_ns: int
    msg_type: str
    trace_id: str
    error_reason: str
    payload_snippet: dict

    def to_dict(self) -> dict:
        return {
            "timestamp_ns": self.timestamp_ns,
            "msg_type": self.msg_type,
            "trace_id": self.trace_id,
            "error_reason": self.error_reason,
            "payload_snippet": self.payload_snippet
        }


class DeadLetterQueue:
    def __init__(self, max_size: int = 10000, dump_path: Optional[str] = None):
        self._messages: list[DroppedMessage] = []
        self._max_size = max_size
        self._dump_path = dump_path
        self._logger = logging.getLogger(__name__)

        if dump_path:
            Path(dump_path).parent.mkdir(parents=True, exist_ok=True)
            self._load_from_file()

    def record(self, msg_type: str, payload: dict, error_reason: str, trace_id: str = "unknown") -> None:
        snippet = {k: payload.get(k) for k in ["article_id", "title", "source_id", "reliability_category"] if k in payload}
        entry = DroppedMessage(
            timestamp_ns=int(time.time_ns()),
            msg_type=msg_type,
            trace_id=trace_id,
            error_reason=error_reason,
            payload_snippet=snippet
        )
        self._messages.append(entry)
        self._logger.warning(f"DLQ: Dropped {msg_type} ({trace_id}): {error_reason}")

        # Evict oldest if max_size exceeded
        while len(self._messages) > self._max_size:
            self._messages.pop(0)

        # Persist on every record for durability
        if self._dump_path:
            self._save_to_file()

    def get_all(self) -> list[dict]:
        return [m.to_dict() for m in self._messages]

    def get_recent(self, count: int = 10) -> list[dict]:
        return [m.to_dict() for m in self._messages[-count:]]

    def clear(self) -> None:
        self._messages.clear()
        if self._dump_path:
            Path(self._dump_path).unlink(missing_ok=True)

    def _save_to_file(self) -> None:
        if self._dump_path:
            data = [m.to_dict() for m in self._messages]
            with open(self._dump_path, "w", encoding="utf-8") as f:
                json.dump(data, f, ensure_ascii=False, indent=2)

    def _load_from_file(self) -> None:
        if self._dump_path and Path(self._dump_path).exists():
            try:
                with open(self._dump_path, "r", encoding="utf-8") as f:
                    data = json.load(f)
                    self._messages = [DroppedMessage(**item) for item in data]
                    self._logger.info(f"DLQ: Loaded {len(self._messages)} messages from {self._dump_path}")
            except (json.JSONDecodeError, KeyError) as e:
                self._logger.error(f"DLQ: Failed to load DLQ file: {e}")
                self._messages = []
