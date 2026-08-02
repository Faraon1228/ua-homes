"""Gunicorn production config for UA Homes backend.

Usage:
  gunicorn -c gunicorn.conf.py app:app

Override any setting via env var prefixed with GUNICORN_:
  GUNICORN_WORKERS=8 gunicorn -c gunicorn.conf.py app:app
"""
import multiprocessing
import os

# ── Workers ─────────────────────────────────────────────────────────────────
# Default: scale with CPU count, but keep a sensible floor for smaller plans.
workers = int(os.environ.get("GUNICORN_WORKERS", max(4, multiprocessing.cpu_count() * 2)))

# Gthread is best for I/O-bound Flask + SQLite/Postgres mix.
worker_class = "gthread"
threads = int(os.environ.get("GUNICORN_THREADS", 4))

# ── Binding ──────────────────────────────────────────────────────────────────
# Railway (and most cloud platforms) inject $PORT. Fall back to 5050 for local dev.
_port = os.environ.get("PORT", os.environ.get("GUNICORN_PORT", "5050"))
bind = os.environ.get("GUNICORN_BIND", f"0.0.0.0:{_port}")

# ── Timeouts ─────────────────────────────────────────────────────────────────
timeout = int(os.environ.get("GUNICORN_TIMEOUT", 30))
graceful_timeout = 20
keepalive = 5

# ── Logging ──────────────────────────────────────────────────────────────────
accesslog = "-"   # stdout
errorlog  = "-"   # stderr
loglevel  = os.environ.get("GUNICORN_LOG_LEVEL", "info")

# ── Process naming ───────────────────────────────────────────────────────────
proc_name = "ua_homes"

# ── Performance tweaks ───────────────────────────────────────────────────────
# Max requests per worker before restart (prevents memory leaks).
max_requests = int(os.environ.get("GUNICORN_MAX_REQUESTS", 1000))
max_requests_jitter = 100   # randomise restarts to avoid thundering herd

# ── Server hooks ─────────────────────────────────────────────────────────────
def on_starting(server):
    server.log.info("UA Homes starting — %d workers × %d threads", workers, threads)

def worker_exit(server, worker):
    server.log.info("Worker exited: PID %s", worker.pid)
