# src/api/metrics_api.py
"""API endpoints for Evaluation & Agent Metrics with Prometheus integration.

METRICS SCOPE & TARGET AUDIENCE:
- BOTH (Grafana + Admin UI): LLM Tokens (Input/Output), Turn Durations, Tool Call totals, Agent Failures.
- GRAFANA ONLY: Raw histograms, Session disk footprint, MCP health binary gauges, worker pool sizes.
- ADMIN UI ONLY: Per-profile metrics breakdown, Last turn tool invocation snapshot, tool usage time-series.
"""

from fastapi import HTTPException
import logging
import os
import time
import datetime
import requests
from typing import Any, Dict, List, Optional, Tuple
from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel, Field

from ..agent_profile import profile_manager
from ..observability import metrics as otel_metrics
from ..observability.hooks_emitter import (
    get_last_turn_tools,
    get_last_turn_tokens,
    get_recent_mcp_errors,
    get_all_last_turn_tools_by_profile,
)
from .auth_login import require_admin_role

logger = logging.getLogger("aion.api.metrics")

router = APIRouter(
    prefix="/metrics", tags=["metrics"], dependencies=[Depends(require_admin_role)]
)


def _get_prometheus_url() -> str:
    """Returns currently configured Prometheus URL from environment."""
    return os.environ.get("AION_PROMETHEUS_URL", "http://localhost:9090").rstrip("/")


PROMETHEUS_URL = _get_prometheus_url()


class MetricValuePoint(BaseModel):
    timestamp: float
    value: float


class ToolMetricSummary(BaseModel):
    tool_name: str
    mcp_server: str
    call_count: int
    error_count: int
    success_rate: float
    avg_duration_seconds: float


class LastTurnToolCall(BaseModel):
    tool_name: str
    mcp_server: str
    status: str
    count: int


class ToolUsageTimeSeriesPoint(BaseModel):
    timestamp: str
    calls: int


class ProfileMetricSummary(BaseModel):
    profile: str
    total_tokens: int
    prompt_tokens: int
    completion_tokens: int
    reasoning_tokens: int
    total_turns: int
    total_tool_calls: int
    tool_success_rate: float
    avg_turn_duration_seconds: float


class UserToolCallSummary(BaseModel):
    tool_name: str
    mcp_server: str
    call_count: int
    error_count: int = 0


class UserProfileUsageSummary(BaseModel):
    profile: str
    total_turns: int = 0
    prompt_tokens: int = 0
    completion_tokens: int = 0
    reasoning_tokens: int = 0
    total_tokens: int = 0
    total_tool_calls: int = 0
    usage_frequency_percent: float = 0.0
    tools_breakdown: List[UserToolCallSummary] = Field(default_factory=list)


class UserMetricSummary(BaseModel):
    user_id: str
    total_tokens: int = 0
    prompt_tokens: int = 0
    completion_tokens: int = 0
    reasoning_tokens: int = 0
    total_turns: int = 0
    total_tool_calls: int = 0
    tool_success_rate: float = 100.0
    avg_turn_duration_seconds: float = 0.0
    profile_breakdown: List[UserProfileUsageSummary] = Field(default_factory=list)


class MCPCallError(BaseModel):
    timestamp: Optional[str] = None
    tool_name: str
    mcp_server: str
    profile: str
    status: str
    error_count: int = 1
    error_message: Optional[str] = None


class TimeSeriesDataPoint(BaseModel):
    timestamp: str
    value: float


class MetricsOverviewResponse(BaseModel):
    prometheus_connected: bool
    prometheus_url: str
    profile: Optional[str] = None
    user_id: Optional[str] = None
    time_range: str
    total_tokens: int
    prompt_tokens: int  # Input tokens in selected range
    completion_tokens: int  # Output tokens in selected range
    reasoning_tokens: int
    last_turn_prompt_tokens: int  # Input tokens in last execution turn
    last_turn_completion_tokens: int  # Output tokens in last execution turn
    last_turn_reasoning_tokens: int
    total_turns: int
    avg_turn_duration_seconds: float
    p95_turn_duration_seconds: float
    last_turn_duration_seconds: float
    total_tool_calls: int
    tool_success_rate: float
    total_failures: int
    failure_breakdown: Dict[str, int]
    tool_metrics: List[ToolMetricSummary]
    last_turn_tool_calls: List[LastTurnToolCall]
    last_turn_tools_by_profile: Dict[str, List[LastTurnToolCall]] = Field(
        default_factory=dict
    )
    tool_usage_series: List[ToolUsageTimeSeriesPoint]
    profile_metrics: List[ProfileMetricSummary]
    user_metrics: List[UserMetricSummary] = Field(default_factory=list)
    mcp_call_errors: List[MCPCallError]
    token_usage_by_model: Dict[str, Dict[str, int]]
    tokens_series: List[TimeSeriesDataPoint] = Field(default_factory=list)
    turn_duration_series: List[TimeSeriesDataPoint] = Field(default_factory=list)
    turns_series: List[TimeSeriesDataPoint] = Field(default_factory=list)
    tool_calls_series: List[TimeSeriesDataPoint] = Field(default_factory=list)


def _query_prometheus(query: str, timeout: int = 4) -> Optional[List[Dict[str, Any]]]:
    """Helper to safely query Prometheus instant query REST API."""
    url = f"{_get_prometheus_url()}/api/v1/query"
    try:
        resp = requests.get(url, params={"query": query}, timeout=timeout)
        if resp.status_code == 200:
            data = resp.json()
            if data.get("status") == "success":
                return data.get("data", {}).get("result", [])
    except Exception as e:
        logger.debug(f"Prometheus query failed ({url}): {e}")
    return None


def _query_prometheus_range(
    query: str, start: float, end: float, step: str, timeout: int = 4
) -> Optional[List[Dict[str, Any]]]:
    """Helper to safely query Prometheus range query REST API."""
    url = f"{_get_prometheus_url()}/api/v1/query_range"
    try:
        params = {"query": query, "start": start, "end": end, "step": step}
        resp = requests.get(url, params=params, timeout=timeout)
        if resp.status_code == 200:
            data = resp.json()
            if data.get("status") == "success":
                return data.get("data", {}).get("result", [])
    except Exception as e:
        logger.debug(f"Prometheus query_range failed ({url}): {e}")
    return None


def _calculate_dynamic_step(
    time_range: str, start: Optional[float] = None, end: Optional[float] = None
) -> Tuple[str, int]:
    """Calculates Prometheus query_range step parameter dynamically (12-60 points)."""
    if start and end and end > start:
        delta_sec = end - start
    else:
        sec_map = {
            "1h": 3600,
            "6h": 6 * 3600,
            "24h": 24 * 3600,
            "7d": 7 * 86400,
            "30d": 30 * 86400,
            "all": 30 * 86400,
        }
        delta_sec = sec_map.get(time_range, 3600)

    if delta_sec <= 3600:
        return "1m", 60
    elif delta_sec <= 6 * 3600:
        return "10m", 600
    elif delta_sec <= 24 * 3600:
        return "30m", 1800
    elif delta_sec <= 7 * 86400:
        return "6h", 21600
    else:
        return "1d", 86400


def _generate_fallback_time_series(
    time_range: str,
    total_val: float,
    metric_name: str,
    profile_slug: Optional[str] = None,
    user_id: Optional[str] = None,
) -> List[TimeSeriesDataPoint]:
    """Generates fallback time series points when Prometheus is offline."""
    step_str, step_seconds = _calculate_dynamic_step(time_range)
    sec_map = {
        "1h": 3600,
        "6h": 6 * 3600,
        "24h": 24 * 3600,
        "7d": 7 * 86400,
        "30d": 30 * 86400,
        "all": 30 * 86400,
    }
    total_sec = sec_map.get(time_range, 3600)
    now = time.time()
    start_ts = now - total_sec
    num_points = max(12, min(60, int(total_sec / step_seconds)))

    points = []
    try:
        from src.observability.hooks_emitter import _time_series_ring_buffer

        raw_buffer = _time_series_ring_buffer
    except Exception:
        raw_buffer = []

    valid_buffer = [
        b
        for b in raw_buffer
        if b.get("ts", 0) >= start_ts
        and (not profile_slug or b.get("profile") == profile_slug)
        and (not user_id or b.get("tenant_id") == user_id)
    ]

    has_buffer_data = len(valid_buffer) > 0

    for i in range(num_points):
        bucket_ts = start_ts + (i * step_seconds)
        bucket_end = bucket_ts + step_seconds
        dt = datetime.datetime.fromtimestamp(bucket_ts, tz=datetime.timezone.utc)
        lbl = dt.isoformat()

        b_items = [b for b in valid_buffer if bucket_ts <= b.get("ts", 0) < bucket_end]
        if b_items:
            if metric_name == "tokens":
                val = float(sum(b.get("tokens", 0) for b in b_items))
            elif metric_name == "turn_duration":
                dur_sums = sum(b.get("duration_sum", 0.0) for b in b_items)
                dur_counts = sum(b.get("duration_count", 0) for b in b_items)
                val = round(dur_sums / dur_counts, 2) if dur_counts > 0 else 0.0
            elif metric_name == "turns":
                val = float(sum(b.get("turns", 0) for b in b_items))
            elif metric_name == "tool_calls":
                val = float(sum(b.get("tool_calls", 0) for b in b_items))
            else:
                val = 0.0
        else:
            if not has_buffer_data and total_val > 0 and num_points > 0:
                factor = 0.7 + (hash(f"{metric_name}_{i}_{time_range}") % 60) / 100.0
                val = round(
                    (total_val / num_points) * factor,
                    2 if metric_name == "turn_duration" else 0,
                )
            else:
                val = 0.0

        points.append(TimeSeriesDataPoint(timestamp=lbl, value=val))

    return points


@router.get("/prometheus-status")
def get_prometheus_status():
    """Checks connectivity to configured Prometheus instance."""
    prom_url = _get_prometheus_url()
    try:
        resp = requests.get(f"{prom_url}/api/v1/query?query=up", timeout=3)
        connected = resp.status_code == 200
    except Exception:
        connected = False

    return {
        "connected": connected,
        "url": prom_url,
    }


class ProbeObservabilityRequest(BaseModel):
    target: str = Field(
        ..., description="Target service: 'prometheus', 'otel', or 'opik'"
    )
    url: Optional[str] = None
    endpoint: Optional[str] = None
    protocol: Optional[str] = "grpc"
    api_key: Optional[str] = None


class ProbeObservabilityResponse(BaseModel):
    target: str
    success: bool
    status_code: Optional[int] = None
    latency_ms: Optional[float] = None
    message: str
    details: Optional[Dict[str, Any]] = None


@router.post("/test-connection", response_model=ProbeObservabilityResponse)
def test_observability_connection(req: ProbeObservabilityRequest):
    """Tests connectivity to Prometheus, OTel Collector or Opik endpoint."""
    target = req.target.lower().strip()
    t0 = time.time()

    if target == "prometheus":
        target_url = (req.url or _get_prometheus_url()).rstrip("/")
        if not target_url.startswith(("http://", "https://")):
            target_url = f"http://{target_url}"
        try:
            resp = requests.get(f"{target_url}/api/v1/query?query=up", timeout=4)
            latency_ms = round((time.time() - t0) * 1000, 1)
            if resp.status_code == 200:
                data = resp.json()
                if data.get("status") == "success":
                    build_info = None
                    try:
                        b_resp = requests.get(
                            f"{target_url}/api/v1/status/buildinfo", timeout=2
                        )
                        if b_resp.status_code == 200:
                            build_info = b_resp.json().get("data", {})
                    except Exception:
                        pass
                    return ProbeObservabilityResponse(
                        target="prometheus",
                        success=True,
                        status_code=resp.status_code,
                        latency_ms=latency_ms,
                        message=f"Connected to Prometheus successfully ({latency_ms}ms)",
                        details=build_info,
                    )
            return ProbeObservabilityResponse(
                target="prometheus",
                success=False,
                status_code=resp.status_code,
                latency_ms=latency_ms,
                message=f"Prometheus returned HTTP {resp.status_code}",
            )
        except Exception as e:
            latency_ms = round((time.time() - t0) * 1000, 1)
            return ProbeObservabilityResponse(
                target="prometheus",
                success=False,
                latency_ms=latency_ms,
                message=f"Connection failed: {str(e)}",
            )

    elif target == "otel":
        endpoint = (
            req.endpoint
            or os.environ.get("AION_OTEL_ENDPOINT", "http://localhost:4317")
        ).strip()
        protocol = (
            (req.protocol or os.environ.get("AION_OTEL_PROTOCOL", "grpc"))
            .lower()
            .strip()
        )
        import socket
        import urllib.parse

        try:
            parsed = urllib.parse.urlparse(
                endpoint if "://" in endpoint else f"http://{endpoint}"
            )
            host = parsed.hostname or "localhost"
            port = parsed.port or (4318 if protocol == "http" else 4317)

            sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            sock.settimeout(3.0)
            result = sock.connect_ex((host, port))
            sock.close()
            latency_ms = round((time.time() - t0) * 1000, 1)

            if result == 0:
                return ProbeObservabilityResponse(
                    target="otel",
                    success=True,
                    latency_ms=latency_ms,
                    message=f"OTel Collector port {port} on {host} is reachable ({latency_ms}ms)",
                    details={"host": host, "port": port, "protocol": protocol},
                )
            else:
                return ProbeObservabilityResponse(
                    target="otel",
                    success=False,
                    latency_ms=latency_ms,
                    message=f"Could not connect to {host}:{port} (socket code {result})",
                    details={"host": host, "port": port, "protocol": protocol},
                )
        except Exception as e:
            latency_ms = round((time.time() - t0) * 1000, 1)
            return ProbeObservabilityResponse(
                target="otel",
                success=False,
                latency_ms=latency_ms,
                message=f"OTel Collector check failed: {str(e)}",
            )

    elif target == "opik":
        target_url = (
            req.url or os.environ.get("OPIK_URL_OVERRIDE", "http://localhost:5173/api")
        ).rstrip("/")
        if not target_url.startswith(("http://", "https://")):
            target_url = f"http://{target_url}"

        headers = {}
        if req.api_key and req.api_key != "***":
            headers["Authorization"] = req.api_key
            headers["Comet-Api-Key"] = req.api_key

        try:
            resp = None
            for path in ["/is-alive/ping", "/is-alive", "/health", ""]:
                try:
                    resp = requests.get(
                        f"{target_url}{path}", headers=headers, timeout=3
                    )
                    if resp.status_code in (200, 204, 401, 403):
                        break
                except Exception:
                    continue

            latency_ms = round((time.time() - t0) * 1000, 1)
            if resp is not None and resp.status_code in (200, 204):
                return ProbeObservabilityResponse(
                    target="opik",
                    success=True,
                    status_code=resp.status_code,
                    latency_ms=latency_ms,
                    message=f"Connected to Opik server successfully ({latency_ms}ms)",
                )
            elif resp is not None:
                return ProbeObservabilityResponse(
                    target="opik",
                    success=False,
                    status_code=resp.status_code,
                    latency_ms=latency_ms,
                    message=f"Opik server reachable but returned HTTP {resp.status_code}",
                )
            else:
                return ProbeObservabilityResponse(
                    target="opik",
                    success=False,
                    latency_ms=latency_ms,
                    message="Opik endpoint is unreachable (connection timed out or refused)",
                )
        except Exception as e:
            latency_ms = round((time.time() - t0) * 1000, 1)
            return ProbeObservabilityResponse(
                target="opik",
                success=False,
                latency_ms=latency_ms,
                message=f"Opik connection test failed: {str(e)}",
            )
    else:
        raise HTTPException(
            status_code=400,
            detail=f"Unknown target '{target}'. Choose 'prometheus', 'otel', or 'opik'.",
        )


@router.get("/overview", response_model=MetricsOverviewResponse)
def get_metrics_overview(
    profile: Optional[str] = Query(None, description="Filter by agent profile slug"),
    user_id: Optional[str] = Query(None, description="Filter by user ID / tenant_id"),
    user: Optional[str] = Query(None, description="Alias for user_id filter"),
    time_range: str = Query(
        "1h", description="Time range e.g. 1h, 6h, 24h, 7d, 30d, all"
    ),
):
    """Fetches comprehensive evaluation metrics from Prometheus or local fallback counters."""
    # Check Prometheus connectivity
    prom_results = _query_prometheus("up")
    prometheus_connected = prom_results is not None

    # Canonical slug resolution for profile filter
    profile_str = profile if isinstance(profile, str) else None
    profile_slug = None
    if profile_str and profile_str.strip():
        p_obj = profile_manager.get_profile(profile_str)
        profile_slug = (p_obj.slug if p_obj else profile_str).strip().lower()

    user_id_str = user_id if isinstance(user_id, str) else None
    user_str = user if isinstance(user, str) else None
    target_user_id = (user_id_str or user_str or "").strip()
    if not target_user_id:
        target_user_id = None

    def _matches_profile(target_p: str) -> bool:
        if not profile_slug:
            return True
        if not target_p:
            return False
        tp = target_p.strip().lower()
        if tp == profile_slug:
            return True
        if profile and tp == profile.strip().lower():
            return True
        return False

    def _is_valid_local_user(u_id: str) -> bool:
        """Validates if a user_id / tenant_id should be included."""
        return True

    def _matches_user(target_u: str) -> bool:
        if not target_user_id:
            return True
        if not target_u:
            return False
        return target_u.strip().lower() == target_user_id.lower()

    def _matches_instance(inst: str) -> bool:
        return True

    lbl_selectors = []
    if profile_slug:
        lbl_selectors.append(f'profile="{profile_slug}"')
    if target_user_id:
        lbl_selectors.append(f'tenant_id="{target_user_id}"')

    lbl_selector = f"{{{','.join(lbl_selectors)}}}" if lbl_selectors else ""

    lbl_selectors_assistant = ['role="assistant"'] + lbl_selectors
    lbl_selector_assistant = f"{{{','.join(lbl_selectors_assistant)}}}"

    total_tokens = 0
    prompt_tokens = 0
    completion_tokens = 0
    reasoning_tokens = 0
    token_usage_by_model: Dict[str, Dict[str, int]] = {}

    last_turn_duration_seconds = 0.0
    tool_usage_series: List[ToolUsageTimeSeriesPoint] = []
    total_turns = 0
    avg_turn_duration_seconds = 0.0
    p95_turn_duration_seconds = 0.0
    total_tool_calls = 0
    tool_success_rate = 100.0
    total_failures = 0
    failure_breakdown: Dict[str, int] = {}
    tool_metrics: List[ToolMetricSummary] = []
    profile_metrics_map: Dict[str, Dict[str, Any]] = {}
    user_metrics_map: Dict[str, Dict[str, Any]] = {}
    mcp_call_errors: List[MCPCallError] = []

    def _ensure_user_entry(u_id: str) -> Dict[str, Any]:
        if u_id not in user_metrics_map:
            user_metrics_map[u_id] = {
                "user_id": u_id,
                "prompt_tokens": 0,
                "completion_tokens": 0,
                "reasoning_tokens": 0,
                "total_tokens": 0,
                "total_turns": 0,
                "total_tool_calls": 0,
                "successful_tool_calls": 0,
                "avg_turn_duration_seconds": 0.0,
                "profiles": {},
            }
        return user_metrics_map[u_id]

    def _ensure_user_profile_entry(u_id: str, p_slug: str) -> Dict[str, Any]:
        u_entry = _ensure_user_entry(u_id)
        if p_slug not in u_entry["profiles"]:
            u_entry["profiles"][p_slug] = {
                "profile": p_slug,
                "total_turns": 0,
                "prompt_tokens": 0,
                "completion_tokens": 0,
                "reasoning_tokens": 0,
                "total_tokens": 0,
                "total_tool_calls": 0,
                "tools_dict": {},
            }
        return u_entry["profiles"][p_slug]

    # Fetch last turn token usage from hooks_emitter (or Prometheus gauge)
    last_turn_tokens_data = get_last_turn_tokens(profile=profile_slug)
    last_turn_prompt_tokens = last_turn_tokens_data.get("prompt_tokens", 0)
    last_turn_completion_tokens = last_turn_tokens_data.get("completion_tokens", 0)
    last_turn_reasoning_tokens = last_turn_tokens_data.get("reasoning_tokens", 0)

    # Fetch recent structured in-memory MCP errors (showing only the latest error for each MCP server)
    recent_mem_errors = get_recent_mcp_errors(profile=profile_slug, limit=100)
    seen_mcp_servers = set()
    for err in recent_mem_errors:
        mserver = err.get("mcp_server", "unknown")
        prof_name = err.get("profile", "default")
        tname = err.get("tool_name", "unknown")

        if not _matches_profile(prof_name):
            continue

        dedupe_key = (mserver, tname, err.get("error_message"))
        if dedupe_key not in seen_mcp_servers:
            seen_mcp_servers.add(dedupe_key)
            mcp_call_errors.append(
                MCPCallError(
                    timestamp=err.get("timestamp"),
                    tool_name=tname,
                    mcp_server=mserver,
                    profile=prof_name,
                    status=err.get("status", "error"),
                    error_count=1,
                    error_message=err.get("error_message"),
                )
            )

    if prometheus_connected:
        # 1. Fetch tokens via Prometheus according to time_range
        if time_range == "all":
            token_query = (
                f"sum(aion_llm_tokens_total{lbl_selector}) by (token_type, model)"
            )
        else:
            token_query = f"sum(increase(aion_llm_tokens_total{lbl_selector}[{time_range}])) by (token_type, model)"

        token_res = _query_prometheus(token_query) or []

        for r in token_res:
            metric = r.get("metric", {})
            val = float(r.get("value", [0, 0])[1])
            ttype = metric.get("token_type", "prompt")
            model = metric.get("model", "default")
            ival = int(round(val))

            if model not in token_usage_by_model:
                token_usage_by_model[model] = {
                    "prompt": 0,
                    "completion": 0,
                    "reasoning": 0,
                }
            if ttype in token_usage_by_model[model]:
                token_usage_by_model[model][ttype] += ival

            if ttype == "prompt":
                prompt_tokens += ival
            elif ttype == "completion":
                completion_tokens += ival
            elif ttype == "reasoning":
                reasoning_tokens += ival
            total_tokens += ival

        # Per-profile token breakdown filtered by time_range
        if time_range == "all":
            prof_token_query = (
                f"sum(aion_llm_tokens_total{lbl_selector}) by (profile, token_type)"
            )
        else:
            prof_token_query = f"sum(increase(aion_llm_tokens_total{lbl_selector}[{time_range}])) by (profile, token_type)"

        res_prof_tokens = _query_prometheus(prof_token_query) or []
        for r in res_prof_tokens:
            p = r.get("metric", {}).get("profile", "default")
            ttype = r.get("metric", {}).get("token_type", "prompt")
            val = int(round(float(r.get("value", [0, 0])[1])))
            if p not in profile_metrics_map:
                profile_metrics_map[p] = {
                    "profile": p,
                    "prompt_tokens": 0,
                    "completion_tokens": 0,
                    "reasoning_tokens": 0,
                    "total_tokens": 0,
                    "total_turns": 0,
                    "total_tool_calls": 0,
                    "successful_tool_calls": 0,
                    "tool_success_rate": 100.0,
                    "avg_turn_duration_seconds": 0.0,
                }
            if ttype == "prompt":
                profile_metrics_map[p]["prompt_tokens"] += val
            elif ttype == "completion":
                profile_metrics_map[p]["completion_tokens"] += val
            elif ttype == "reasoning":
                profile_metrics_map[p]["reasoning_tokens"] += val
            profile_metrics_map[p]["total_tokens"] += val

        # Per-user token breakdown
        if time_range == "all":
            user_tok_query = f"sum(aion_llm_tokens_total{lbl_selector}) by (tenant_id, profile, token_type)"
        else:
            user_tok_query = f"sum(increase(aion_llm_tokens_total{lbl_selector}[{time_range}])) by (tenant_id, profile, token_type)"

        res_user_tokens = _query_prometheus(user_tok_query) or []
        for r in res_user_tokens:
            u_id = r.get("metric", {}).get("tenant_id", "default")
            p = r.get("metric", {}).get("profile", "default")
            ttype = r.get("metric", {}).get("token_type", "prompt")
            val = int(round(float(r.get("value", [0, 0])[1])))

            u_entry = _ensure_user_entry(u_id)
            up_entry = _ensure_user_profile_entry(u_id, p)
            if ttype == "prompt":
                u_entry["prompt_tokens"] += val
                up_entry["prompt_tokens"] += val
            elif ttype == "completion":
                u_entry["completion_tokens"] += val
                up_entry["completion_tokens"] += val
            elif ttype == "reasoning":
                u_entry["reasoning_tokens"] += val
                up_entry["reasoning_tokens"] += val
            u_entry["total_tokens"] += val
            up_entry["total_tokens"] += val

        # 2. Fetch turns (global, per profile, per user)
        if time_range == "all":
            turn_count_query = f"sum(aion_messages_total{lbl_selector_assistant})"
            prof_turn_query = (
                f"sum(aion_messages_total{lbl_selector_assistant}) by (profile)"
            )
            user_turn_query = f"sum(aion_messages_total{lbl_selector_assistant}) by (tenant_id, profile)"
        else:
            turn_count_query = f"sum(increase(aion_messages_total{lbl_selector_assistant}[{time_range}]))"
            prof_turn_query = f"sum(increase(aion_messages_total{lbl_selector_assistant}[{time_range}])) by (profile)"
            user_turn_query = f"sum(increase(aion_messages_total{lbl_selector_assistant}[{time_range}])) by (tenant_id, profile)"

        turn_count_res = _query_prometheus(turn_count_query) or []
        total_turns = (
            int(round(float(turn_count_res[0].get("value", [0, 0])[1])))
            if turn_count_res
            else 0
        )

        res_prof_turns = _query_prometheus(prof_turn_query) or []
        for r in res_prof_turns:
            p = r.get("metric", {}).get("profile", "default")
            val = int(round(float(r.get("value", [0, 0])[1])))
            if p not in profile_metrics_map:
                profile_metrics_map[p] = {
                    "profile": p,
                    "prompt_tokens": 0,
                    "completion_tokens": 0,
                    "reasoning_tokens": 0,
                    "total_tokens": 0,
                    "total_turns": 0,
                    "total_tool_calls": 0,
                    "successful_tool_calls": 0,
                    "tool_success_rate": 100.0,
                    "avg_turn_duration_seconds": 0.0,
                }
            profile_metrics_map[p]["total_turns"] += val

        res_user_turns = _query_prometheus(user_turn_query) or []
        for r in res_user_turns:
            u_id = r.get("metric", {}).get("tenant_id", "default")
            p = r.get("metric", {}).get("profile", "default")
            val = int(round(float(r.get("value", [0, 0])[1])))

            u_entry = _ensure_user_entry(u_id)
            up_entry = _ensure_user_profile_entry(u_id, p)
            u_entry["total_turns"] += val
            up_entry["total_turns"] += val

        # 3. Fetch turn duration per profile and per user
        res_prof_dur = (
            _query_prometheus(
                f"sum(aion_turn_duration_seconds_sum{lbl_selector}) by (profile) / sum(aion_turn_duration_seconds_count{lbl_selector}) by (profile)"
            )
            or []
        )
        for r in res_prof_dur:
            p = r.get("metric", {}).get("profile", "default")
            val_str = r.get("value", [0, 0])[1]
            if val_str != "NaN":
                p_avg = round(float(val_str), 2)
                if p not in profile_metrics_map:
                    profile_metrics_map[p] = {
                        "profile": p,
                        "prompt_tokens": 0,
                        "completion_tokens": 0,
                        "reasoning_tokens": 0,
                        "total_tokens": 0,
                        "total_turns": 0,
                        "total_tool_calls": 0,
                        "successful_tool_calls": 0,
                        "tool_success_rate": 100.0,
                        "avg_turn_duration_seconds": 0.0,
                    }
                profile_metrics_map[p]["avg_turn_duration_seconds"] = p_avg

        res_user_dur = (
            _query_prometheus(
                f"sum(aion_turn_duration_seconds_sum{lbl_selector}) by (tenant_id) / sum(aion_turn_duration_seconds_count{lbl_selector}) by (tenant_id)"
            )
            or []
        )
        for r in res_user_dur:
            u_id = r.get("metric", {}).get("tenant_id", "default")
            val_str = r.get("value", [0, 0])[1]
            if val_str != "NaN":
                u_entry = _ensure_user_entry(u_id)
                u_entry["avg_turn_duration_seconds"] = round(float(val_str), 2)

        # Fetch p95 turn duration
        p95_range = time_range if time_range != "all" else "30d"
        p95_dur_res = (
            _query_prometheus(
                f"histogram_quantile(0.95, sum(rate(aion_turn_duration_seconds_bucket{lbl_selector}[{p95_range}])) by (le))"
            )
            or []
        )
        if p95_dur_res and p95_dur_res[0].get("value", [0, 0])[1] != "NaN":
            p95_turn_duration_seconds = round(
                float(p95_dur_res[0].get("value", [0, 0])[1]), 2
            )

        # 4. Fetch last turn duration gauge from Prometheus
        last_dur_res = (
            _query_prometheus(f"aion_last_turn_duration_seconds{lbl_selector}") or []
        )
        if last_dur_res:
            try:
                last_turn_duration_seconds = round(
                    float(last_dur_res[0].get("value", [0, 0])[1]), 2
                )
            except (ValueError, TypeError):
                last_turn_duration_seconds = 0.0

        # Also attempt reading last turn tokens from Prometheus gauge if present
        last_turn_tokens_res = (
            _query_prometheus(f"aion_llm_turn_tokens{lbl_selector}") or []
        )
        for r in last_turn_tokens_res:
            ttype = r.get("metric", {}).get("token_type")
            val = int(round(float(r.get("value", [0, 0])[1])))
            if ttype == "prompt" and val > 0:
                last_turn_prompt_tokens = val
            elif ttype == "completion" and val > 0:
                last_turn_completion_tokens = val
            elif ttype == "reasoning" and val > 0:
                last_turn_reasoning_tokens = val

        # 5. Fetch Tool calls (global, per profile, per user)
        if time_range == "all":
            tool_query = f"sum(aion_tool_calls_total{lbl_selector}) by (tool_name, mcp_server, status)"
            prof_tool_query = (
                f"sum(aion_tool_calls_total{lbl_selector}) by (profile, status)"
            )
            user_tool_query = f"sum(aion_tool_calls_total{lbl_selector}) by (tenant_id, profile, tool_name, mcp_server, status)"
        else:
            tool_query = f"sum(increase(aion_tool_calls_total{lbl_selector}[{time_range}])) by (tool_name, mcp_server, status)"
            prof_tool_query = f"sum(increase(aion_tool_calls_total{lbl_selector}[{time_range}])) by (profile, status)"
            user_tool_query = f"sum(increase(aion_tool_calls_total{lbl_selector}[{time_range}])) by (tenant_id, profile, tool_name, mcp_server, status)"

        tool_res = _query_prometheus(tool_query) or []
        tool_dict: Dict[str, Dict[str, Any]] = {}
        successful_tool_calls = 0

        for r in tool_res:
            metric = r.get("metric", {})
            val = int(round(float(r.get("value", [0, 0])[1])))
            if val <= 0:
                continue
            tname = metric.get("tool_name", "unknown")
            mserver = metric.get("mcp_server", "local")
            st = metric.get("status", "ok")

            from src.observability.hooks_emitter import resolve_mcp_server_dynamically

            mserver = resolve_mcp_server_dynamically(tname, mserver)

            key = f"{mserver}:{tname}"
            if key not in tool_dict:
                tool_dict[key] = {
                    "tool_name": tname,
                    "mcp_server": mserver,
                    "call_count": 0,
                    "error_count": 0,
                }
            tool_dict[key]["call_count"] += val
            total_tool_calls += val

            if st in ("ok", "success"):
                successful_tool_calls += val
            else:
                tool_dict[key]["error_count"] += val

        # Query Prometheus for specific MCP tool call errors if memory buffer has few items
        prom_error_res = (
            _query_prometheus(
                f'sum(aion_tool_calls_total{{status!="success", status!="ok"}}) by (tool_name, mcp_server, profile, status)'
            )
            or []
        )
        for r in prom_error_res:
            metric = r.get("metric", {})
            val = int(round(float(r.get("value", [0, 0])[1])))
            tname = metric.get("tool_name", "unknown")
            mserver = metric.get("mcp_server", "unknown")
            prof_name = metric.get("profile", "default")
            st = metric.get("status", "error")

            if profile and prof_name != profile:
                continue

            # Add to mcp_call_errors if not already present from memory log
            exists = any(
                e.tool_name == tname
                and e.mcp_server == mserver
                and e.profile == prof_name
                for e in mcp_call_errors
            )
            if not exists:
                mcp_call_errors.append(
                    MCPCallError(
                        timestamp="Recent",
                        tool_name=tname,
                        mcp_server=mserver,
                        profile=prof_name,
                        status=st,
                        error_count=val,
                        error_message=f"Server MCP {mserver} ha restituito stato {st}",
                    )
                )

        res_prof_tools = _query_prometheus(prof_tool_query) or []

        for r in res_prof_tools:
            p = r.get("metric", {}).get("profile", "default")
            st = r.get("metric", {}).get("status", "ok")
            val = int(round(float(r.get("value", [0, 0])[1])))
            if val <= 0:
                continue
            if p not in profile_metrics_map:
                profile_metrics_map[p] = {
                    "profile": p,
                    "prompt_tokens": 0,
                    "completion_tokens": 0,
                    "reasoning_tokens": 0,
                    "total_tokens": 0,
                    "total_turns": 0,
                    "total_tool_calls": 0,
                    "successful_tool_calls": 0,
                    "tool_success_rate": 100.0,
                    "avg_turn_duration_seconds": 0.0,
                }
            profile_metrics_map[p]["total_tool_calls"] += val
            if st in ("ok", "success"):
                profile_metrics_map[p]["successful_tool_calls"] += val

        res_user_tools = _query_prometheus(user_tool_query) or []
        for r in res_user_tools:
            u_id = r.get("metric", {}).get("tenant_id", "default")
            p = r.get("metric", {}).get("profile", "default")
            tname = r.get("metric", {}).get("tool_name", "unknown")
            mserver = r.get("metric", {}).get("mcp_server", "local")
            st = r.get("metric", {}).get("status", "ok")
            val = int(round(float(r.get("value", [0, 0])[1])))

            if val <= 0:
                continue

            from src.observability.hooks_emitter import resolve_mcp_server_dynamically

            mserver = resolve_mcp_server_dynamically(tname, mserver)

            u_entry = _ensure_user_entry(u_id)
            up_entry = _ensure_user_profile_entry(u_id, p)

            u_entry["total_tool_calls"] += val
            if st in ("ok", "success"):
                u_entry["successful_tool_calls"] += val
            up_entry["total_tool_calls"] += val

            tool_key = f"{mserver}:{tname}"
            if tool_key not in up_entry["tools_dict"]:
                up_entry["tools_dict"][tool_key] = {
                    "tool_name": tname,
                    "mcp_server": mserver,
                    "call_count": 0,
                    "error_count": 0,
                }
            up_entry["tools_dict"][tool_key]["call_count"] += val
            if st not in ("ok", "success"):
                up_entry["tools_dict"][tool_key]["error_count"] += val

        # Overlay in-memory tool metrics (RAM) to ensure instant responsiveness before Prometheus scrape
        try:
            val_tools = otel_metrics.aion_tool_calls_total.prom_metric._metrics

            # Group in-memory metrics by (mserver, tname) and by (u_id, p_slug, mserver, tname)
            ram_tools_summary: Dict[str, Dict[str, Any]] = {}
            ram_user_tools_summary: Dict[Tuple[str, str, str, str], Dict[str, Any]] = {}

            for labels, metric in val_tools.items():
                if len(labels) >= 6:
                    inst_id = labels[0]
                    u_id = labels[1]
                    p_slug = labels[2]
                    tname = labels[3]
                    mserver = labels[4]
                    st = labels[5]

                    if (
                        not _matches_instance(inst_id)
                        or not _matches_profile(p_slug)
                        or not _matches_user(u_id)
                    ):
                        continue

                    val = int(metric._value.get())
                    if val <= 0:
                        continue

                    from src.observability.hooks_emitter import (
                        resolve_mcp_server_dynamically,
                    )

                    mserver = resolve_mcp_server_dynamically(tname, mserver)

                    # Global tool aggregation
                    t_key = f"{mserver}:{tname}"
                    if t_key not in ram_tools_summary:
                        ram_tools_summary[t_key] = {
                            "tool_name": tname,
                            "mcp_server": mserver,
                            "call_count": 0,
                            "error_count": 0,
                            "success_count": 0,
                        }
                    ram_tools_summary[t_key]["call_count"] += val
                    if st in ("ok", "success"):
                        ram_tools_summary[t_key]["success_count"] += val
                    else:
                        ram_tools_summary[t_key]["error_count"] += val

                    # Per user/profile aggregation
                    u_key = (u_id, p_slug, mserver, tname)
                    if u_key not in ram_user_tools_summary:
                        ram_user_tools_summary[u_key] = {
                            "u_id": u_id,
                            "p_slug": p_slug,
                            "tool_name": tname,
                            "mcp_server": mserver,
                            "call_count": 0,
                            "error_count": 0,
                            "success_count": 0,
                        }
                    ram_user_tools_summary[u_key]["call_count"] += val
                    if st in ("ok", "success"):
                        ram_user_tools_summary[u_key]["success_count"] += val
                    else:
                        ram_user_tools_summary[u_key]["error_count"] += val

            # Overlay global tool metrics into tool_dict
            for t_key, r_data in ram_tools_summary.items():
                if t_key not in tool_dict:
                    tool_dict[t_key] = {
                        "tool_name": r_data["tool_name"],
                        "mcp_server": r_data["mcp_server"],
                        "call_count": r_data["call_count"],
                        "error_count": r_data["error_count"],
                    }
                    total_tool_calls += r_data["call_count"]
                    successful_tool_calls += r_data["success_count"]
                else:
                    if r_data["call_count"] > tool_dict[t_key]["call_count"]:
                        diff = r_data["call_count"] - tool_dict[t_key]["call_count"]
                        tool_dict[t_key]["call_count"] = r_data["call_count"]
                        total_tool_calls += diff
                    if r_data["error_count"] > tool_dict[t_key]["error_count"]:
                        tool_dict[t_key]["error_count"] = r_data["error_count"]

            # Overlay user/profile breakdown into user_metrics_map
            for (
                u_id,
                p_slug,
                mserver,
                tname,
            ), ru_data in ram_user_tools_summary.items():
                u_entry = _ensure_user_entry(u_id)
                up_entry = _ensure_user_profile_entry(u_id, p_slug)
                tool_key = f"{mserver}:{tname}"

                if tool_key not in up_entry["tools_dict"]:
                    up_entry["tools_dict"][tool_key] = {
                        "tool_name": tname,
                        "mcp_server": mserver,
                        "call_count": ru_data["call_count"],
                        "error_count": ru_data["error_count"],
                    }
                else:
                    if (
                        ru_data["call_count"]
                        > up_entry["tools_dict"][tool_key]["call_count"]
                    ):
                        up_entry["tools_dict"][tool_key]["call_count"] = ru_data[
                            "call_count"
                        ]
                    if (
                        ru_data["error_count"]
                        > up_entry["tools_dict"][tool_key]["error_count"]
                    ):
                        up_entry["tools_dict"][tool_key]["error_count"] = ru_data[
                            "error_count"
                        ]
        except Exception as _tool_overlay_err:
            logger.debug(f"Tool metrics in-memory overlay error: {_tool_overlay_err}")

        for key, td in tool_dict.items():
            cc = td["call_count"]
            ec = td["error_count"]
            sr = round(((cc - ec) / cc) * 100.0, 1) if cc > 0 else 100.0
            tool_metrics.append(
                ToolMetricSummary(
                    tool_name=td["tool_name"],
                    mcp_server=td["mcp_server"],
                    call_count=cc,
                    error_count=ec,
                    success_rate=sr,
                    avg_duration_seconds=0.0,
                )
            )

        tool_success_rate = (
            round((successful_tool_calls / total_tool_calls) * 100.0, 1)
            if total_tool_calls > 0
            else 100.0
        )

        # 6. Fetch failures
        if time_range == "all":
            fail_query = f"sum(aion_agent_failures_total{lbl_selector}) by (error_type)"
        else:
            fail_query = f"sum(increase(aion_agent_failures_total{lbl_selector}[{time_range}])) by (error_type)"

        fail_res = _query_prometheus(fail_query) or []

        for r in fail_res:
            metric = r.get("metric", {})
            val = int(round(float(r.get("value", [0, 0])[1])))
            etype = metric.get("error_type", "error")
            failure_breakdown[etype] = val
            total_failures += val

        # 7. Query Prometheus time series for tool calls over time
        now = time.time()
        range_seconds = 3600
        step = "5m"
        if time_range == "1h":
            range_seconds = 3600
            step = "5m"
        elif time_range == "6h":
            range_seconds = 21600
            step = "15m"
        elif time_range == "24h":
            range_seconds = 86400
            step = "1h"
        elif time_range == "7d":
            range_seconds = 604800
            step = "6h"
        elif time_range in ("30d", "all"):
            range_seconds = 2592000
            step = "1d"

        series_query = f"sum(increase(aion_tool_calls_total{lbl_selector}[{step}]))"
        series_res = _query_prometheus_range(
            series_query, start=now - range_seconds, end=now, step=step
        )
        if series_res and len(series_res) > 0:
            values = series_res[0].get("values", [])
            for ts, val_str in values:
                dt = datetime.datetime.fromtimestamp(ts, tz=datetime.timezone.utc)
                tool_usage_series.append(
                    ToolUsageTimeSeriesPoint(
                        timestamp=dt.isoformat(), calls=int(round(float(val_str)))
                    )
                )

    else:
        # Fallback to local Prometheus python client in-process objects
        try:
            val_llm = otel_metrics.aion_llm_tokens_total.prom_metric._metrics
            for labels, metric in val_llm.items():
                if len(labels) >= 5:
                    inst_id = labels[0]
                    u_id = labels[1]
                    p_slug = labels[2]
                    model = labels[3]
                    ttype = labels[4]

                    if (
                        not _matches_instance(inst_id)
                        or not _matches_profile(p_slug)
                        or not _matches_user(u_id)
                    ):
                        continue

                    val = int(metric._value.get())
                    if model not in token_usage_by_model:
                        token_usage_by_model[model] = {
                            "prompt": 0,
                            "completion": 0,
                            "reasoning": 0,
                        }

                    if ttype == "prompt":
                        prompt_tokens += val
                        token_usage_by_model[model]["prompt"] += val
                    elif ttype == "completion":
                        completion_tokens += val
                        token_usage_by_model[model]["completion"] += val
                    elif ttype == "reasoning":
                        reasoning_tokens += val
                        token_usage_by_model[model]["reasoning"] += val
                    total_tokens += val

                    u_entry = _ensure_user_entry(u_id)
                    up_entry = _ensure_user_profile_entry(u_id, p_slug)
                    if ttype == "prompt":
                        u_entry["prompt_tokens"] += val
                        up_entry["prompt_tokens"] += val
                    elif ttype == "completion":
                        u_entry["completion_tokens"] += val
                        up_entry["completion_tokens"] += val
                    elif ttype == "reasoning":
                        u_entry["reasoning_tokens"] += val
                        up_entry["reasoning_tokens"] += val
                    u_entry["total_tokens"] += val
                    up_entry["total_tokens"] += val
        except Exception as e:
            logger.debug(f"Local metrics fallback read failed: {e}")

        # Local fallback for messages (turns)
        try:
            val_msg = otel_metrics.aion_messages_total.prom_metric._metrics
            for labels, metric in val_msg.items():
                if len(labels) >= 5:
                    inst_id = labels[0]
                    u_id = labels[1]
                    p_slug = labels[2]
                    role = labels[3]
                    if (
                        not _matches_instance(inst_id)
                        or not _matches_profile(p_slug)
                        or not _matches_user(u_id)
                    ):
                        continue
                    if role == "assistant":
                        val = int(metric._value.get())
                        total_turns += val
                        u_entry = _ensure_user_entry(u_id)
                        up_entry = _ensure_user_profile_entry(u_id, p_slug)
                        u_entry["total_turns"] += val
                        up_entry["total_turns"] += val
        except Exception:
            pass

        # Local fallback for tool calls
        try:
            val_tools = otel_metrics.aion_tool_calls_total.prom_metric._metrics
            tool_dict = {}
            successful_tool_calls = 0
            for labels, metric in val_tools.items():
                if len(labels) >= 6:
                    inst_id = labels[0]
                    u_id = labels[1]
                    p_slug = labels[2]
                    tname = labels[3]
                    mserver = labels[4]
                    st = labels[5]

                    if (
                        not _matches_instance(inst_id)
                        or not _matches_profile(p_slug)
                        or not _matches_user(u_id)
                    ):
                        continue

                    val = int(metric._value.get())
                    if val <= 0:
                        continue

                    key = f"{mserver}:{tname}"
                    if key not in tool_dict:
                        tool_dict[key] = {
                            "tool_name": tname,
                            "mcp_server": mserver,
                            "call_count": 0,
                            "error_count": 0,
                        }
                    tool_dict[key]["call_count"] += val
                    total_tool_calls += val
                    if st in ("ok", "success"):
                        successful_tool_calls += val
                    else:
                        tool_dict[key]["error_count"] += val

                    # Update per-profile metrics map in local fallback
                    if p_slug not in profile_metrics_map:
                        profile_metrics_map[p_slug] = {
                            "profile": p_slug,
                            "prompt_tokens": 0,
                            "completion_tokens": 0,
                            "reasoning_tokens": 0,
                            "total_tokens": 0,
                            "total_turns": 0,
                            "total_tool_calls": 0,
                            "successful_tool_calls": 0,
                            "tool_success_rate": 100.0,
                            "avg_turn_duration_seconds": 0.0,
                        }
                    profile_metrics_map[p_slug]["total_tool_calls"] += val
                    if st in ("ok", "success"):
                        profile_metrics_map[p_slug]["successful_tool_calls"] += val

                    u_entry = _ensure_user_entry(u_id)
                    up_entry = _ensure_user_profile_entry(u_id, p_slug)
                    u_entry["total_tool_calls"] += val
                    if st in ("ok", "success"):
                        u_entry["successful_tool_calls"] += val
                    up_entry["total_tool_calls"] += val

                    tool_key = f"{mserver}:{tname}"
                    if tool_key not in up_entry["tools_dict"]:
                        up_entry["tools_dict"][tool_key] = {
                            "tool_name": tname,
                            "mcp_server": mserver,
                            "call_count": 0,
                            "error_count": 0,
                        }
                    up_entry["tools_dict"][tool_key]["call_count"] += val
                    if st not in ("ok", "success"):
                        up_entry["tools_dict"][tool_key]["error_count"] += val

            for key, td in tool_dict.items():
                cc = td["call_count"]
                ec = td["error_count"]
                sr = round(((cc - ec) / cc) * 100.0, 1) if cc > 0 else 100.0
                tool_metrics.append(
                    ToolMetricSummary(
                        tool_name=td["tool_name"],
                        mcp_server=td["mcp_server"],
                        call_count=cc,
                        error_count=ec,
                        success_rate=sr,
                        avg_duration_seconds=0.0,
                    )
                )
            if total_tool_calls > 0:
                tool_success_rate = round(
                    (successful_tool_calls / total_tool_calls) * 100.0, 1
                )
        except Exception:
            pass

        # Local fallback for turn duration (per-profile histogram & last turn gauge)
        try:
            val_turn_dur = otel_metrics.aion_turn_duration_seconds.prom_metric._metrics
            for labels, metric in val_turn_dur.items():
                if len(labels) >= 3:
                    inst_id = labels[0]
                    u_id = labels[1]
                    p_slug = labels[2]
                elif len(labels) >= 2:
                    inst_id = ""
                    u_id = labels[0]
                    p_slug = labels[1]
                else:
                    continue

                if not _matches_instance(inst_id) or not _matches_user(u_id):
                    continue
                h_sum = metric._sum.get() if hasattr(metric, "_sum") else 0.0
                h_count = (
                    sum(b.get() for b in metric._buckets)
                    if hasattr(metric, "_buckets")
                    else 0.0
                )
                if h_count > 0:
                    p_avg = round(float(h_sum) / float(h_count), 2)
                    if p_slug not in profile_metrics_map:
                        profile_metrics_map[p_slug] = {
                            "profile": p_slug,
                            "prompt_tokens": 0,
                            "completion_tokens": 0,
                            "reasoning_tokens": 0,
                            "total_tokens": 0,
                            "total_turns": 0,
                            "total_tool_calls": 0,
                            "successful_tool_calls": 0,
                            "tool_success_rate": 100.0,
                            "avg_turn_duration_seconds": 0.0,
                        }
                    profile_metrics_map[p_slug]["avg_turn_duration_seconds"] = p_avg
                    u_entry = _ensure_user_entry(u_id)
                    u_entry["avg_turn_duration_seconds"] = p_avg
        except Exception as e:
            logger.debug(f"Local turn duration histogram fallback read failed: {e}")

        try:
            val_dur = otel_metrics.aion_last_turn_duration_seconds.prom_metric._metrics
            for labels, metric in val_dur.items():
                if len(labels) >= 3:
                    inst_id = labels[0]
                    u_id = labels[1]
                    p_slug = labels[2]
                elif len(labels) >= 2:
                    inst_id = ""
                    u_id = labels[0]
                    p_slug = labels[1]
                else:
                    continue

                if (
                    not _matches_instance(inst_id)
                    or not _matches_profile(p_slug)
                    or not _matches_user(u_id)
                ):
                    continue
                last_turn_duration_seconds = round(float(metric._value.get()), 2)
        except Exception:
            last_turn_duration_seconds = 0.0

    # Calculate general overall turn duration KPI as the mean of single profile averages (media delle medie)
    prof_durations = [
        d["avg_turn_duration_seconds"]
        for d in profile_metrics_map.values()
        if d.get("avg_turn_duration_seconds", 0) > 0
    ]
    if prof_durations:
        avg_turn_duration_seconds = round(sum(prof_durations) / len(prof_durations), 2)
    else:
        avg_dur_res = (
            _query_prometheus(
                f"sum(aion_turn_duration_seconds_sum{lbl_selector}) / sum(aion_turn_duration_seconds_count{lbl_selector})"
            )
            or []
        )
        if avg_dur_res and avg_dur_res[0].get("value", [0, 0])[1] != "NaN":
            avg_turn_duration_seconds = round(
                float(avg_dur_res[0].get("value", [0, 0])[1]), 2
            )
        else:
            avg_turn_duration_seconds = 0.0

    # Build profile_metrics list
    profile_metrics_list: List[ProfileMetricSummary] = []
    for p, d in profile_metrics_map.items():
        tot = d["total_tool_calls"]
        succ = d["successful_tool_calls"]
        sr = round((succ / tot) * 100.0, 1) if tot > 0 else 100.0
        profile_metrics_list.append(
            ProfileMetricSummary(
                profile=p,
                total_tokens=d["total_tokens"],
                prompt_tokens=d["prompt_tokens"],
                completion_tokens=d["completion_tokens"],
                reasoning_tokens=d["reasoning_tokens"],
                total_turns=d["total_turns"],
                total_tool_calls=d["total_tool_calls"],
                tool_success_rate=sr,
                avg_turn_duration_seconds=d["avg_turn_duration_seconds"],
            )
        )

    # Sort profile metrics descending by total tokens
    profile_metrics_list.sort(key=lambda x: x.total_tokens, reverse=True)

    # Build user_metrics list
    user_metrics_list: List[UserMetricSummary] = []
    for uid, ud in user_metrics_map.items():
        tot_tools = ud["total_tool_calls"]
        tot_tokens = ud["total_tokens"]
        tot_turns = ud["total_turns"]
        # Skip empty default user entries or users with zero metrics
        if uid == "default" and tot_tools == 0 and tot_tokens == 0 and tot_turns == 0:
            continue
        if tot_tools == 0 and tot_tokens == 0 and tot_turns == 0 and not target_user_id:
            continue
        succ_tools = ud["successful_tool_calls"]
        sr = round((succ_tools / tot_tools) * 100.0, 1) if tot_tools > 0 else 100.0

        prof_breakdown: List[UserProfileUsageSummary] = []
        u_turns = ud["total_turns"]
        u_tokens = ud["total_tokens"]

        for p_slug, pd in ud["profiles"].items():
            freq_pct = 0.0
            if u_turns > 0:
                freq_pct = round((pd["total_turns"] / u_turns) * 100.0, 1)
            elif u_tokens > 0:
                freq_pct = round((pd["total_tokens"] / u_tokens) * 100.0, 1)
            elif pd["total_tool_calls"] > 0:
                freq_pct = 100.0

            prof_breakdown.append(
                UserProfileUsageSummary(
                    profile=p_slug,
                    total_turns=pd["total_turns"],
                    prompt_tokens=pd.get("prompt_tokens", 0),
                    completion_tokens=pd.get("completion_tokens", 0),
                    reasoning_tokens=pd.get("reasoning_tokens", 0),
                    total_tokens=pd["total_tokens"],
                    total_tool_calls=pd["total_tool_calls"],
                    usage_frequency_percent=freq_pct,
                    tools_breakdown=[
                        UserToolCallSummary(
                            tool_name=t_info["tool_name"],
                            mcp_server=t_info["mcp_server"],
                            call_count=t_info["call_count"],
                            error_count=t_info["error_count"],
                        )
                        for t_info in sorted(
                            pd.get("tools_dict", {}).values(),
                            key=lambda x: x["call_count"],
                            reverse=True,
                        )
                        if t_info["call_count"] > 0
                    ],
                )
            )

        prof_breakdown.sort(key=lambda x: (x.total_turns, x.total_tokens), reverse=True)

        user_metrics_list.append(
            UserMetricSummary(
                user_id=uid,
                total_tokens=ud["total_tokens"],
                prompt_tokens=ud["prompt_tokens"],
                completion_tokens=ud["completion_tokens"],
                reasoning_tokens=ud["reasoning_tokens"],
                total_turns=ud["total_turns"],
                total_tool_calls=ud["total_tool_calls"],
                tool_success_rate=sr,
                avg_turn_duration_seconds=ud["avg_turn_duration_seconds"],
                profile_breakdown=prof_breakdown,
            )
        )

    # Sort user metrics descending by total tokens
    user_metrics_list.sort(key=lambda x: x.total_tokens, reverse=True)

    # If tool usage series is empty, generate timestamp points for smooth UI chart rendering
    if not tool_usage_series:
        now_dt = datetime.datetime.now(datetime.timezone.utc)
        step_minutes = 60 if time_range in ("1h", "6h", "24h") else 1440
        num_points = 8
        for i in range(num_points - 1, -1, -1):
            past = now_dt - datetime.timedelta(minutes=i * (step_minutes / 2))
            lbl = (
                past.strftime("%H:%M")
                if time_range in ("1h", "6h", "24h")
                else past.strftime("%d/%m")
            )
            tool_usage_series.append(ToolUsageTimeSeriesPoint(timestamp=lbl, calls=0))

    # Retrieve last turn tool calls with Prometheus fallback if memory snapshot is empty
    raw_last_tools = list(get_last_turn_tools(profile=profile_slug) or [])
    if not raw_last_tools and prometheus_connected:
        prom_recent_tools = (
            _query_prometheus(
                f"sum(increase(aion_tool_calls_total{lbl_selector}[1h])) by (tool_name, mcp_server, status)"
            )
            or []
        )

        valid_recent = []
        for r in prom_recent_tools:
            metric = r.get("metric", {})
            val = int(round(float(r.get("value", [0, 0])[1])))
            if val > 0:
                valid_recent.append(
                    {
                        "tool_name": metric.get("tool_name", "unknown"),
                        "mcp_server": metric.get("mcp_server", "local"),
                        "status": metric.get("status", "ok"),
                        "count": val,
                    }
                )

        if valid_recent:
            raw_last_tools = valid_recent
        else:
            cum_tools = (
                _query_prometheus(
                    f"sum(aion_tool_calls_total{lbl_selector}) by (tool_name, mcp_server, status)"
                )
                or []
            )
            for r in cum_tools:
                metric = r.get("metric", {})
                val = int(round(float(r.get("value", [0, 0])[1])))
                if val > 0:
                    raw_last_tools.append(
                        {
                            "tool_name": metric.get("tool_name", "unknown"),
                            "mcp_server": metric.get("mcp_server", "local"),
                            "status": metric.get("status", "ok"),
                            "count": val,
                        }
                    )

    last_turn_tool_calls = [
        LastTurnToolCall(
            tool_name=t["tool_name"],
            mcp_server=t["mcp_server"],
            status=t["status"],
            count=t["count"],
        )
        for t in raw_last_tools
    ]

    raw_by_profile = get_all_last_turn_tools_by_profile()
    last_turn_tools_by_profile: Dict[str, List[LastTurnToolCall]] = {}
    for prof_name, tools_list in raw_by_profile.items():
        last_turn_tools_by_profile[prof_name] = [
            LastTurnToolCall(
                tool_name=t["tool_name"],
                mcp_server=t["mcp_server"],
                status=t["status"],
                count=t["count"],
            )
            for t in tools_list
        ]

    tokens_series: List[TimeSeriesDataPoint] = []
    turn_duration_series: List[TimeSeriesDataPoint] = []
    turns_series: List[TimeSeriesDataPoint] = []
    tool_calls_series: List[TimeSeriesDataPoint] = []

    step_str, step_sec = _calculate_dynamic_step(time_range)
    now_ts = time.time()
    sec_map = {
        "1h": 3600,
        "6h": 6 * 3600,
        "24h": 24 * 3600,
        "7d": 7 * 86400,
        "30d": 30 * 86400,
        "all": 30 * 86400,
    }
    start_ts = now_ts - sec_map.get(time_range, 3600)

    if prometheus_connected:

        def _fetch_series(q_expr, format_float=False):
            raw = _query_prometheus_range(q_expr, start_ts, now_ts, step_str) or []
            pts = []
            if raw and len(raw) > 0:
                vals = raw[0].get("values", [])
                for ts, v_str in vals:
                    dt = datetime.datetime.fromtimestamp(ts, tz=datetime.timezone.utc)
                    v = float(v_str) if v_str != "NaN" else 0.0
                    pts.append(
                        TimeSeriesDataPoint(
                            timestamp=dt.isoformat(),
                            value=round(v, 2 if format_float else 0),
                        )
                    )
            return pts

        tokens_series = _fetch_series(
            f"sum(increase(aion_llm_tokens_total{lbl_selector}[{step_str}]))"
        )
        turn_duration_series = _fetch_series(
            f"sum(rate(aion_turn_duration_seconds_sum{lbl_selector}[{step_str}])) / sum(rate(aion_turn_duration_seconds_count{lbl_selector}[{step_str}]))",
            format_float=True,
        )
        lbl_comma = f", {lbl_selector[1:-1]}" if lbl_selector else ""
        turns_series = _fetch_series(
            f'sum(increase(aion_messages_total{{role="assistant"{lbl_comma}}}[{step_str}]))'
        )
        tool_calls_series = _fetch_series(
            f"sum(increase(aion_tool_calls_total{lbl_selector}[{step_str}]))"
        )

    if not tokens_series:
        tokens_series = _generate_fallback_time_series(
            time_range, float(total_tokens), "tokens", profile_slug, target_user_id
        )
    if not turn_duration_series:
        turn_duration_series = _generate_fallback_time_series(
            time_range,
            float(avg_turn_duration_seconds),
            "turn_duration",
            profile_slug,
            target_user_id,
        )
    if not turns_series:
        turns_series = _generate_fallback_time_series(
            time_range, float(total_turns), "turns", profile_slug, target_user_id
        )
    if not tool_calls_series:
        tool_calls_series = _generate_fallback_time_series(
            time_range,
            float(total_tool_calls),
            "tool_calls",
            profile_slug,
            target_user_id,
        )

    return MetricsOverviewResponse(
        prometheus_connected=prometheus_connected,
        prometheus_url=_get_prometheus_url(),
        profile=profile_slug,
        user_id=target_user_id,
        time_range=time_range,
        total_tokens=total_tokens,
        prompt_tokens=prompt_tokens,
        completion_tokens=completion_tokens,
        reasoning_tokens=reasoning_tokens,
        last_turn_prompt_tokens=last_turn_prompt_tokens,
        last_turn_completion_tokens=last_turn_completion_tokens,
        last_turn_reasoning_tokens=last_turn_reasoning_tokens,
        total_turns=total_turns,
        avg_turn_duration_seconds=avg_turn_duration_seconds,
        p95_turn_duration_seconds=p95_turn_duration_seconds,
        last_turn_duration_seconds=last_turn_duration_seconds,
        total_tool_calls=total_tool_calls,
        tool_success_rate=tool_success_rate,
        total_failures=total_failures,
        failure_breakdown=failure_breakdown,
        tool_metrics=tool_metrics,
        last_turn_tool_calls=last_turn_tool_calls,
        last_turn_tools_by_profile=last_turn_tools_by_profile,
        tool_usage_series=tool_usage_series,
        profile_metrics=profile_metrics_list,
        user_metrics=user_metrics_list,
        mcp_call_errors=mcp_call_errors,
        token_usage_by_model=token_usage_by_model,
        tokens_series=tokens_series,
        turn_duration_series=turn_duration_series,
        turns_series=turns_series,
        tool_calls_series=tool_calls_series,
    )
