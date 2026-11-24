# MID Logic - Phase 7 Engine Interface Spec

Engine contracts (msgspec.Structs), verification middleware, and DLQ implementation.

## Overview

Phase 7 implements a robust message broker interface with the following components:

### Core Components

- **`schemas/contract.py`**: `msgspec.Struct` based message schemas (7 structures)
- **`schemas/verify.py`**: Envelope verification middleware (2-path validation)
- **`schemas/dlq.py`**: Dead Letter Queue implementation
- **`schemas/queue.py`**: MessageBroker (asyncio.Queue based)

### Policy & Configuration

- **`schemas/dlq_policy.yaml`**: DLQ operational policies (TTL, max_size, replay)

### Testing

- **`tests/test_schemas.py`**: Schema and verification tests (8+7+6=21 cases)
- **`tests/test_dlq.py`**: DLQ tests
- **`tests/test_queue.py`**: Queue tests

## Quick Start

### Creating an Envelope

```python
from schemas.contract import Envelope, Payload

# Create a valid envelope
payload = Payload(data="test", insight="sync")
env = Envelope(
    spec_version="7.0",
    msg_type="sync",
    trace_id="trace-123",
    span_id="span-456",
    timestamp_ns=1234567890,
    payload=payload
)
```

### Verification

```python
from schemas.verify import validate_envelope

valid, result = validate_envelope(env)
# Returns (True, payload) or (False, error_info)
```

### DLQ Handling

```python
from schemas.queue import MessageBroker
from schemas.dlq import DeadLetterQueue

# Create queues with policy configuration
policy = DeadLetterQueue(
    max_size=10000,
    ttl_days=7,
    replay_mode="manual"
)
```

## API Contracts

All message schemas are defined in `schemas/contract.py` and follow the single-source principle.

See `schemas/verify.py` for the 2-path validation flow:
1. **Normal path**: Valid envelope → next queue
2. **Error path**: Invalid envelope → DLQ (incremented `rejected_dlq` counter)

## Development Status

- ✅ **Phase 7-1 to 7-4**: Completed (Engine Interface Spec)
- 🔄 **Phase 7-5**: In progress (Multi-channel distribution)
- 📝 **Pending**: `dlq_policy.yaml` configuration and test stabilization

## PR Status

This repository represents the **current state** after the Phase 7 implementation.

### Notable Commits

- **Initial (3b07af3)**: Massive commit (~5000 lines) containing full Phase 7 implementation
- **Fix (8ecb2d9)**: Added `dlq_policy.yaml` and test stabilization
- **Current**: Ready for Phase 7-5 (multi-channel distribution)

## Next Steps

1. Review and integrate `dlq_policy.yaml` into the main codebase
2. Stabilize `test_latency_tracking` environment dependencies
3. Proceed with Phase 7-5 (multi-channel distribution) implementation
