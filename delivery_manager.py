import time
import hashlib
import logging
try:
    from prometheus_client import Counter
except ImportError:
    class Counter:
        def __init__(self, name, description): self.name = name
        def inc(self, amount=1): pass


# Prometheus Metrics
DELIVERY_TOTAL = Counter('delivery_total', 'Total delivery attempts')
DELIVERY_SUCCESS = Counter('delivery_success', 'Successful deliveries')
DELIVERY_FAILURE = Counter('delivery_failure', 'Failed deliveries')
DLQ_COUNT = Counter('dlq_count', 'Messages moved to DLQ')

class DeliveryManager:
    def __init__(self, dlq_handler=None, max_retries=3):
        self.dlq_handler = dlq_handler
        self.max_retries = max_retries
        self.processed_hashes = set()
        self.logger = logging.getLogger(__name__)

    def _generate_idempotency_key(self, data):
        return hashlib.sha256(str(data).encode()).hexdigest()

    def process_message(self, message):
        DELIVERY_TOTAL.inc()
        idempotency_key = self._generate_idempotency_key(message)
        
        if idempotency_key in self.processed_hashes:
            self.logger.warning(f"Duplicate message detected: {idempotency_key}")
            return False

        attempts = 0
        success = False
        while attempts < self.max_retries:
            try:
                # Simulate processing logic
                self._do_work(message)
                success = True
                break
            except Exception as e:
                attempts += 1
                self.logger.error(f"Attempt {attempts} failed: {e}")
        
        if success:
            self.processed_hashes.add(idempotency_key)
            DELIVERY_SUCCESS.inc()
            return True
        else:
            DELIVERY_FAILURE.inc()
            if self.dlq_handler:
                self.dlq_handler.send_to_dlq(message)
                DLQ_COUNT.inc()
            return False

    def _do_work(self, message):
        # Placeholder for actual work
        if "fail" in str(message):
            raise Exception("Processing error")
        pass
