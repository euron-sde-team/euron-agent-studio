"""Prometheus metrics, exposed at GET /metrics (and on WORKER_METRICS_PORT by the worker).

One API process per container (scale out with containers, not uvicorn workers), so the
default registry is accurate without multiprocess mode.
"""

from __future__ import annotations

from prometheus_client import Counter, Gauge, Histogram

HTTP_REQUESTS = Counter(
    "agentstudio_http_requests_total",
    "HTTP requests by route template.",
    ["method", "route", "status"],
)
HTTP_LATENCY = Histogram(
    "agentstudio_http_request_duration_seconds",
    "HTTP request latency by route template.",
    ["method", "route"],
    buckets=(0.005, 0.01, 0.025, 0.05, 0.1, 0.25, 0.5, 1, 2.5, 5, 10, 30),
)
RUNS_STARTED = Counter("agentstudio_runs_started_total", "Runs created, by trigger.", ["trigger"])
RUNS_FINISHED = Counter(
    "agentstudio_runs_finished_total", "Runs that reached a final or waiting state.", ["status"]
)
RUN_DURATION = Histogram(
    "agentstudio_run_duration_seconds",
    "Wall-clock time of one execution slice of a run (claim to finish or pause).",
    buckets=(0.1, 0.25, 0.5, 1, 2.5, 5, 10, 30, 60, 120, 300, 900),
)
ACTIVE_RUNS = Gauge("agentstudio_active_runs", "Runs executing in this process.")
STEPS = Counter(
    "agentstudio_steps_total", "Node executions by type and final status.", ["node_type", "status"]
)
STEP_LATENCY = Histogram(
    "agentstudio_step_duration_seconds",
    "Node execution latency by type.",
    ["node_type"],
    buckets=(0.005, 0.01, 0.05, 0.1, 0.25, 0.5, 1, 2.5, 5, 10, 30, 60, 120),
)
MODEL_CALLS = Counter(
    "agentstudio_model_calls_total",
    "Model completions by provider and outcome (ok, error, cached).",
    ["provider", "outcome"],
)
MODEL_LATENCY = Histogram(
    "agentstudio_model_call_duration_seconds",
    "Model completion latency by provider.",
    ["provider"],
    buckets=(0.01, 0.05, 0.1, 0.25, 0.5, 1, 2.5, 5, 10, 30, 60, 120),
)
TOKENS = Counter(
    "agentstudio_tokens_total", "Model tokens by provider and kind.", ["provider", "kind"]
)
COST = Counter("agentstudio_cost_usd_total", "Model cost in US dollars by provider.", ["provider"])
HTTP_TOOL_REQUESTS = Counter(
    "agentstudio_http_tool_requests_total",
    "HTTP request node calls by outcome (ok, http_error, blocked, error).",
    ["outcome"],
)
WEBHOOKS = Counter(
    "agentstudio_webhook_deliveries_total",
    "Inbound webhook deliveries by outcome.",
    ["outcome"],
)
REAPED = Counter(
    "agentstudio_reaped_total",
    "Reaper actions by kind: run (lost heartbeat), message (lost message resent), approval.",
    ["kind"],
)
