import os

DATABASE_URL = os.getenv(
    "DATABASE_URL",
    "postgresql://postgres:postgres@postgres:5432/teda"
)

# How long to keep runs/events/points in DB
EVENT_TTL_SECONDS = int(os.getenv("EVENT_TTL_SECONDS", "86400"))

# Cleanup loop interval
CLEANUP_INTERVAL_SECONDS = int(os.getenv("CLEANUP_INTERVAL_SECONDS", "60"))

# SSE: max events returned per DB poll
EVENTS_FETCH_LIMIT = int(os.getenv("EVENTS_FETCH_LIMIT", "200"))

# SSE: how often to emit keepalive when no events
KEEPALIVE_SECONDS = int(os.getenv("KEEPALIVE_SECONDS", "10"))

# Worker: emit partial events every N steps (if you use it)
EMIT_PARTIAL_EVERY_N_STEPS = int(os.getenv("EMIT_PARTIAL_EVERY_N_STEPS", "1"))

POLL_INTERVAL_SECONDS = float(os.getenv("POLL_INTERVAL_SECONDS", "0.5"))

