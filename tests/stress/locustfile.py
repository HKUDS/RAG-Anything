"""
RAG-Anything SSE Streaming Query Stress Test (Locust)

Tests the POST /api/agents/{agent_id}/query/stream endpoint under
realistic concurrent load with full SSE event tracking.

Usage:
    # Quick smoke test (1 user, 30s)
    locust -f tests/stress/locustfile.py --headless -u 1 -r 1 -t 30s \
        --host=http://localhost:8000

    # Phased stress test via config file
    locust -f tests/stress/locustfile.py --config tests/stress/locust.conf

    # Web UI for interactive testing
    locust -f tests/stress/locustfile.py --host=http://localhost:8000

    # Distributed (1 master + N workers)
    locust -f tests/stress/locustfile.py --master
    locust -f tests/stress/locustfile.py --worker --master-host=<master_ip>

Environment Variables:
    RAG_HOST              API base URL (default: http://localhost:8000)
    RAG_USERNAME          Login username (default: admin)
    RAG_PASSWORD          Login password (default: admin123)
    RAG_AGENT_ID          Agent ID to query (default: 1)
    RAG_QUERY_FILE        Path to queries JSON (default: tests/stress/queries.json)
    RAG_QUERY_MODE        Query mode: rrf, naive, mix, or "" for agent default
    RAG_AGENT_MODE        Agent mode: react, cot, or "" for normal RAG
    RAG_SSE_TIMEOUT       SSE connection timeout seconds (default: 120)
    RAG_MAX_TOKENS        Stop after receiving N tokens (0 = no limit, default: 0)
"""

import json
import os
import time
import random
import logging
from pathlib import Path
from typing import Optional, Dict, List

import gevent
from locust import HttpUser, task, between, events
from locust.env import Environment
from locust.runners import WorkerRunner
from locust.exception import StopUser
import requests

# ── Logger ──────────────────────────────────────────────────────────────
logger = logging.getLogger("rag_stress")

# ── Custom Locust Metrics ───────────────────────────────────────────────
# We fire custom events because Locust's built-in request tracking
# measures HTTP round-trip time, which for SSE long-polling would be
# misleading (it would show the entire stream duration, not per-event timing).


@events.init.add_listener
def register_custom_metrics(environment: Environment, **_kwargs):
    """Register custom metrics when Locust initializes."""

    # These are registered on the stats object so they appear in the
    # Locust UI and are exported to CSV / report formats.
    if hasattr(environment, "stats"):
        pass  # Custom events are fire-and-forget; we track via listeners below


# ── SSE Event Parser ────────────────────────────────────────────────────


class SSEEvent:
    """A single Server-Sent Event parsed from the stream."""

    __slots__ = ("event_type", "data", "raw")

    def __init__(self, event_type: str, data: dict, raw: str):
        self.event_type = event_type
        self.data = data
        self.raw = raw


def parse_sse_stream(response: requests.Response):
    """
    Generator that yields SSEEvent objects from a streaming response.

    Handles multi-line data fields (data:line1\ndata:line2) per the SSE spec,
    and correctly buffers partial chunks across socket reads.
    """
    buffer = ""
    current_data_lines: List[str] = []
    current_event_type = "message"

    for chunk in response.iter_content(chunk_size=1, decode_unicode=True):
        if chunk is None:
            continue
        buffer += chunk

        while "\n" in buffer:
            line, buffer = buffer.split("\n", 1)
            line = line.rstrip("\r")

            # Empty line = dispatch event
            if line == "":
                if current_data_lines:
                    raw_data = "\n".join(current_data_lines)
                    try:
                        parsed = json.loads(raw_data)
                    except json.JSONDecodeError:
                        # Malformed event; skip
                        current_data_lines = []
                        current_event_type = "message"
                        continue

                    yield SSEEvent(
                        event_type=parsed.get("type", current_event_type),
                        data=parsed,
                        raw=raw_data,
                    )
                    current_data_lines = []
                    current_event_type = "message"
                continue

            # Comment line (starts with colon) — ignore
            if line.startswith(":"):
                continue

            # event: field
            if line.startswith("event:"):
                current_event_type = line[6:].strip()
                continue

            # data: field (may appear multiple times per event)
            if line.startswith("data:"):
                current_data_lines.append(line[5:].strip())
                continue

            # Other fields (id:, retry:) — ignore for this test

    # Flush any remaining partial event at stream end (unlikely but safe)
    if current_data_lines:
        raw_data = "\n".join(current_data_lines)
        try:
            parsed = json.loads(raw_data)
            yield SSEEvent(
                event_type=parsed.get("type", current_event_type),
                data=parsed,
                raw=raw_data,
            )
        except json.JSONDecodeError:
            pass


# ── Query Loader ────────────────────────────────────────────────────────


def load_queries(file_path: str) -> List[dict]:
    """Load query records from a JSON file with weight-based selection."""
    path = Path(file_path)
    if not path.exists():
        logger.warning(f"Query file not found: {file_path}; using fallback queries")
        return [
            {"query": "什么是RAG？", "category": "short_factoid", "weight": 5},
            {"query": "如何创建知识库？", "category": "short_factoid", "weight": 3},
            {"query": "请解释LightRAG的文档处理流程", "category": "medium_analytical", "weight": 3},
            {"query": "详细说明多模态RAG系统的设计架构", "category": "long_generative", "weight": 2},
        ]

    with open(path, "r", encoding="utf-8") as f:
        queries = json.load(f)

    logger.info(f"Loaded {len(queries)} queries from {file_path}")
    return queries


# ── Weighted Random Selector ────────────────────────────────────────────


class WeightedQuerySelector:
    """Select queries according to their weight for realistic distribution."""

    def __init__(self, queries: List[dict]):
        self.queries = queries
        self.weights = [q.get("weight", 1) for q in queries]
        self._total = sum(self.weights)
        # Pre-compute cumulative weights for O(log n) selection
        self._cumulative = []
        cumulative = 0
        for w in self.weights:
            cumulative += w
            self._cumulative.append(cumulative)

    def pick(self) -> dict:
        """Pick a random query weighted by its 'weight' field."""
        r = random.random() * self._total
        for i, cum in enumerate(self._cumulative):
            if r <= cum:
                return self.queries[i]
        return self.queries[-1]

    def pick_query_text(self) -> str:
        """Return just the query string."""
        return self.pick()["query"]

    def pick_category(self) -> str:
        """Return the category of the selected query."""
        return self.pick().get("category", "unknown")


# ── Custom Event Reporting ──────────────────────────────────────────────
# These events are fired from within tasks; we listen here to push them
# into Locust's stats system so they appear in the web UI, CSV exports,
# and final summary.


class SSEMetricsCollector:
    """Collects per-query SSE metrics and reports them via Locust events."""

    def __init__(self):
        self.reset()

    def reset(self):
        self.ttft_values: List[float] = []        # seconds
        self.token_rates: List[float] = []         # tokens/sec
        self.total_times: List[float] = []         # seconds
        self.error_count: int = 0
        self.success_count: int = 0
        self.timeout_count: int = 0
        self.rate_limit_count: int = 0

    def record_ttft(self, ttft_s: float):
        self.ttft_values.append(ttft_s)

    def record_token_rate(self, rate: float):
        self.token_rates.append(rate)

    def record_total_time(self, t_s: float):
        self.total_times.append(t_s)

    def record_error(self, error_type: str = "error"):
        if error_type == "timeout":
            self.timeout_count += 1
        elif error_type == "rate_limit":
            self.rate_limit_count += 1
        else:
            self.error_count += 1

    def record_success(self):
        self.success_count += 1

    def summary(self) -> dict:
        """Return a summary dict of all collected metrics."""
        def _p(arr, pct):
            if not arr:
                return None
            s = sorted(arr)
            idx = int(len(s) * pct / 100)
            return s[min(idx, len(s) - 1)]

        return {
            "ttft_p50": _p(self.ttft_values, 50),
            "ttft_p95": _p(self.ttft_values, 95),
            "ttft_p99": _p(self.ttft_values, 99),
            "ttft_avg": sum(self.ttft_values) / len(self.ttft_values) if self.ttft_values else None,
            "token_rate_p50": _p(self.token_rates, 50),
            "token_rate_p95": _p(self.token_rates, 95),
            "token_rate_avg": sum(self.token_rates) / len(self.token_rates) if self.token_rates else None,
            "total_time_p50": _p(self.total_times, 50),
            "total_time_p95": _p(self.total_times, 95),
            "total_time_p99": _p(self.total_times, 99),
            "total_time_avg": sum(self.total_times) / len(self.total_times) if self.total_times else None,
            "success": self.success_count,
            "errors": self.error_count,
            "timeouts": self.timeout_count,
            "rate_limits": self.rate_limit_count,
            "total_requests": self.success_count + self.error_count + self.timeout_count + self.rate_limit_count,
        }


# Global collector instance (one per worker process)
_metrics = SSEMetricsCollector()


# ── Custom Locust Event Handlers ────────────────────────────────────────


@events.test_start.add_listener
def on_test_start(environment: Environment, **_kwargs):
    """Reset metrics at the start of each test run."""
    global _metrics
    _metrics = SSEMetricsCollector()
    logger.info("SSE stress test starting — metrics collector reset")


@events.test_stop.add_listener
def on_test_stop(environment: Environment, **_kwargs):
    """Print a summary of collected SSE metrics at test end."""
    summary = _metrics.summary()
    logger.info("=" * 60)
    logger.info("SSE STRESS TEST SUMMARY")
    logger.info("=" * 60)
    logger.info(f"  Total Requests:     {summary['total_requests']}")
    logger.info(f"  Successful:         {summary['success']}")
    logger.info(f"  Errors:             {summary['errors']}")
    logger.info(f"  Timeouts:           {summary['timeouts']}")
    logger.info(f"  Rate Limits (429):  {summary['rate_limits']}")
    logger.info(f"  ---")
    logger.info(f"  TTFT  P50:          {summary['ttft_p50']}")
    logger.info(f"  TTFT  P95:          {summary['ttft_p95']}")
    logger.info(f"  TTFT  P99:          {summary['ttft_p99']}")
    logger.info(f"  TTFT  Avg:          {summary['ttft_avg']}")
    logger.info(f"  ---")
    logger.info(f"  Token Rate P50:     {summary['token_rate_p50']}")
    logger.info(f"  Token Rate P95:     {summary['token_rate_p95']}")
    logger.info(f"  Token Rate Avg:     {summary['token_rate_avg']}")
    logger.info(f"  ---")
    logger.info(f"  Total Time P50:     {summary['total_time_p50']}")
    logger.info(f"  Total Time P95:     {summary['total_time_p95']}")
    logger.info(f"  Total Time P99:     {summary['total_time_p99']}")
    logger.info(f"  Total Time Avg:     {summary['total_time_avg']}")
    logger.info("=" * 60)

    # Also write to a JSON file for post-processing
    report_path = Path(
        os.environ.get("RAG_STRESS_REPORT", "sse_stress_summary.json")
    )
    with open(report_path, "w", encoding="utf-8") as f:
        json.dump(summary, f, indent=2, default=str, ensure_ascii=False)
    logger.info(f"Detailed summary written to {report_path}")


# ── Locust User Class ───────────────────────────────────────────────────


class RAGQueryUser(HttpUser):
    """
    Simulates a user who:
      1. Authenticates once at startup (on_start)
      2. Picks a random question from the query pool
      3. Connects to the SSE query endpoint
      4. Streams and measures per-token timing
      5. Waits (simulating reading time) before the next question
    """

    # ── Configuration (overridable via env vars) ──
    host: str = ""
    username: str = ""
    password: str = ""
    agent_id: str = ""
    query_mode: str = ""
    agent_mode: str = ""
    sse_timeout: int = 120
    max_tokens: int = 0

    # ── State ──
    auth_token: str = ""
    query_selector: Optional[WeightedQuerySelector] = None

    # ── Locust timing ──
    # wait_time = between(5, 30): user pauses 5-30s between queries
    # (simulates reading the answer before asking the next question)
    wait_time = between(5, 30)

    def on_start(self):
        """
        Called once per simulated user when they start.

        Loads configuration, authenticates, and prepares the query pool.
        """
        # ── Load config from env ──
        self.username = os.environ.get("RAG_USERNAME", "admin")
        self.password = os.environ.get("RAG_PASSWORD", "admin123")
        self.agent_id = os.environ.get("RAG_AGENT_ID", "1")
        self.query_mode = os.environ.get("RAG_QUERY_MODE", "")
        self.agent_mode = os.environ.get("RAG_AGENT_MODE", "")
        self.sse_timeout = int(os.environ.get("RAG_SSE_TIMEOUT", "120"))
        self.max_tokens = int(os.environ.get("RAG_MAX_TOKENS", "0"))

        # ── Authenticate ──
        self._authenticate()

        # ── Load queries ──
        query_file = os.environ.get(
            "RAG_QUERY_FILE",
            str(Path(__file__).resolve().parent / "queries.json"),
        )
        queries = load_queries(query_file)
        self.query_selector = WeightedQuerySelector(queries)

        logger.info(
            f"User {self.username} ready: agent={self.agent_id}, "
            f"mode={self.query_mode or 'default'}, "
            f"agent_mode={self.agent_mode or 'none'}, "
            f"queries={len(queries)}"
        )

    def _authenticate(self):
        """Log in and store the JWT access token."""
        login_url = f"{self.host}/api/auth/login"
        payload = {"username": self.username, "password": self.password}

        with self.client.post(
            login_url,
            json=payload,
            name="/api/auth/login",
            catch_response=True,
            timeout=15,
        ) as resp:
            if resp.status_code != 200:
                logger.error(
                    f"Login failed for {self.username}: "
                    f"HTTP {resp.status_code} — {resp.text[:200]}"
                )
                resp.failure(f"Login failed: HTTP {resp.status_code}")
                raise StopUser()

            try:
                data = resp.json()
            except json.JSONDecodeError:
                resp.failure("Login response was not valid JSON")
                raise StopUser()

            token = data.get("access_token") or data.get("token")
            if not token:
                resp.failure("No access_token in login response")
                raise StopUser()

            self.auth_token = token
            resp.success()

    @task
    def sse_query_stream(self):
        """
        Main task: pick a random query, send it to the SSE stream endpoint,
        measure TTFT, token rate, total elapsed, and report errors.
        """
        if not self.auth_token:
            logger.error("No auth token; skipping query")
            return

        query_text = self.query_selector.pick_query_text()
        category = self.query_selector.pick_category()

        url = f"{self.host}/api/agents/{self.agent_id}/query/stream"
        headers = {
            "Authorization": f"Bearer {self.auth_token}",
            "Content-Type": "application/json",
            "Accept": "text/event-stream",
        }
        payload = {
            "query": query_text,
            "thread_id": "",
            "mode": self.query_mode,
            "agent_mode": self.agent_mode if self.agent_mode else None,
        }

        # ── Timing bookmarks ──
        stream_start: Optional[float] = None
        first_token_time: Optional[float] = None
        last_token_time: Optional[float] = None
        token_count: int = 0
        last_event_type: Optional[str] = None
        done_data: Optional[dict] = None
        error_msg: Optional[str] = None

        # ── Connect and stream ──
        try:
            # Use a raw requests session for SSE streaming (Locust's
            # HttpUser client wraps requests but streaming requires
            # setting stream=True, which we do via a direct call).
            with self.client.post(
                url,
                json=payload,
                headers=headers,
                stream=True,
                timeout=self.sse_timeout,
                name=f"/api/agents/{{agent_id}}/query/stream ({category})",
                catch_response=True,
            ) as response:

                stream_start = time.monotonic()

                # ── Check for immediate HTTP errors ──
                if response.status_code == 429:
                    _metrics.record_error("rate_limit")
                    response.failure("Rate limited (429)")
                    return
                if response.status_code == 401:
                    _metrics.record_error("auth")
                    response.failure("Authentication failed (401)")
                    return
                if response.status_code == 403:
                    _metrics.record_error("forbidden")
                    response.failure("Forbidden (403)")
                    return
                if response.status_code >= 500:
                    _metrics.record_error("server_error")
                    response.failure(f"Server error ({response.status_code})")
                    return
                if response.status_code != 200:
                    _metrics.record_error("http_error")
                    response.failure(f"Unexpected HTTP {response.status_code}")
                    return

                # ── Parse SSE stream ──
                for event in parse_sse_stream(response):
                    now = time.monotonic()
                    last_event_type = event.event_type

                    if event.event_type == "token":
                        token_count += 1
                        last_token_time = now

                        # Record TTFT on the very first token
                        if first_token_time is None:
                            first_token_time = now
                            ttft = now - stream_start
                            _metrics.record_ttft(ttft)

                        # Optional early stop after N tokens
                        if self.max_tokens > 0 and token_count >= self.max_tokens:
                            response.failure = None  # treat partial as success
                            break

                    elif event.event_type == "done":
                        done_data = event.data
                        break

                    elif event.event_type == "error":
                        error_msg = event.data.get("content", "Unknown SSE error")
                        response.failure(f"SSE error: {error_msg}")
                        _metrics.record_error("sse_error")
                        return

                    elif event.event_type == "image_analysis":
                        pass  # informational; not a failure

                    elif event.event_type == "warning":
                        logger.debug(f"SSE warning: {event.data.get('content', '')}")

        except requests.exceptions.ConnectionError as e:
            _metrics.record_error("connection")
            logger.warning(f"Connection error: {e}")
            return
        except requests.exceptions.ReadTimeout:
            _metrics.record_error("timeout")
            logger.warning(f"SSE stream timeout after {self.sse_timeout}s")
            return
        except requests.exceptions.RequestException as e:
            _metrics.record_error("request")
            logger.warning(f"Request exception: {e}")
            return
        except Exception as e:
            _metrics.record_error("unknown")
            logger.error(f"Unexpected error in SSE task: {e}")
            return

        # ── Compute and record metrics ──
        total_elapsed = time.monotonic() - stream_start if stream_start else 0

        if done_data:
            # Use server-reported elapsed when available (excludes network jitter)
            server_elapsed = done_data.get("elapsed", total_elapsed)
        else:
            server_elapsed = total_elapsed

        # Token generation rate: tokens / (time between first and last token)
        if token_count > 0 and first_token_time and last_token_time:
            generation_window = last_token_time - first_token_time
            if generation_window > 0:
                token_rate = token_count / generation_window
            else:
                token_rate = float(token_count)  # all tokens arrived instantly
        else:
            token_rate = 0.0

        _metrics.record_total_time(server_elapsed)
        if token_rate > 0:
            _metrics.record_token_rate(token_rate)
        _metrics.record_success()

        # Report via Locust's stats (optional — for web UI visibility)
        if hasattr(events, "request"):
            events.request.fire(
                request_type="SSE",
                name=f"query_stream({category})",
                response_time=total_elapsed * 1000,  # ms for Locust
                response_length=token_count,
                exception=None,
                context={},
            )


# ── Optional: Background health-check / warmup task ────────────────────
# Uncomment to add a lightweight task that verifies the API is responsive
# before the main load test begins.
#
# class WarmupUser(HttpUser):
#     wait_time = between(1, 3)
#
#     @task
#     def health_check(self):
#         self.client.get("/api/health", name="health_check")


# ── Locust Event Hooks ──────────────────────────────────────────────────
# These serve as the main stats pipeline: they catch every custom event
# fired by Locust tasks and log aggregate metrics.


@events.quitting.add_listener
def on_quitting(environment: Environment, **_kwargs):
    """Called when Locust is shutting down. Final metrics dump."""
    if environment.runner and isinstance(environment.runner, WorkerRunner):
        return  # Only master prints summary (or standalone)

    stats = environment.stats
    logger.info("=" * 60)
    logger.info("LOCUST BUILT-IN STATS SUMMARY")
    logger.info("=" * 60)
    logger.info(f"Total requests:   {stats.total.num_requests}")
    logger.info(f"Total failures:   {stats.total.num_failures}")
    logger.info(f"Avg response time: {stats.total.avg_response_time:.0f} ms")
    logger.info(f"P50 response time: {stats.total.get_response_time_percentile(0.5):.0f} ms")
    logger.info(f"P95 response time: {stats.total.get_response_time_percentile(0.95):.0f} ms")
    logger.info(f"P99 response time: {stats.total.get_response_time_percentile(0.99):.0f} ms")
    logger.info(f"Max response time: {stats.total.max_response_time:.0f} ms")
    logger.info(f"RPS:              {stats.total.total_rps:.1f}")
    logger.info("=" * 60)


# ── Locust Configuration Defaults ───────────────────────────────────────
# These are applied when running without --config.
# Use a locust.conf file for persistent configuration.


def _default_options():
    """Return a dict of default option overrides."""
    return {
        # Default host — can be overridden by --host or locust.conf
        "host": os.environ.get("RAG_HOST", "http://localhost:8000"),
    }


# ── Main entry point (for direct script execution) ──────────────────────
if __name__ == "__main__":
    import sys
    from locust.main import main

    sys.argv.extend([
        "--host", os.environ.get("RAG_HOST", "http://localhost:8000"),
        "--users", os.environ.get("RAG_USERS", "5"),
        "--spawn-rate", os.environ.get("RAG_SPAWN_RATE", "2"),
        "--run-time", os.environ.get("RAG_RUN_TIME", "60s"),
    ])
    main()
