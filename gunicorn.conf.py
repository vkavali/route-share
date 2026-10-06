"""Single-process Railway worker configuration for in-memory live leases."""

from __future__ import annotations

import os

raw_port = os.environ.get("PORT", "").strip()
try:
    port = int(raw_port)
except ValueError as exc:
    raise RuntimeError("Railway must provide PORT as an integer.") from exc
if not 1 <= port <= 65535:
    raise RuntimeError("Railway PORT must be between 1 and 65535.")

bind = f"0.0.0.0:{port}"
workers = 1
worker_class = "gthread"
threads = 8
preload_app = False
accesslog = None
errorlog = "-"
loglevel = "info"

# A single worker keeps the in-memory live-location lease store coherent.
# Leave the app import to the worker process; create_app starts its expiry timer.
