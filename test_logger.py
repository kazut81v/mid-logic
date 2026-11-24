from logger import log_event
import os

# Verify path and log
print(f"Testing log directory creation...")
log_file = "OneDrive/Vault/Memory/Feedback/logs/test_log.jsonl"
# Note: Since logger.py creates a filename with today's date, 
# I'll just check if the directory exists and if I can write.

print(f"Attempting to log test event...")
try:
    log_event(
        engine_id="Test-Engine",
        action_type="verification",
        correlation_id="test-001",
        input_summary="Testing logger module",
        output_summary="Success",
        metadata={"status": "verified"}
    )
    print("Log entry successful.")
    
    # Check if file was created
    files = os.listdir("OneDrive/Vault/Memory/Feedback/logs")
    print(f"Files in log directory: {files}")
except Exception as e:
    print(f"Error during test: {e}")
