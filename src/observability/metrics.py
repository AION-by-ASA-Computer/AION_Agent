import logging
from prometheus_client import (
    Counter as PromCounter,
    Histogram as PromHistogram,
    Gauge as PromGauge,
)

logger = logging.getLogger(__name__)

class OTelPrometheusCounter:
    def __init__(self, name, documentation, labelnames=()):
        self.name = name
        self.documentation = documentation
        self.labelnames = labelnames
        self.prom_metric = PromCounter(name, documentation, labelnames)
        self.otel_instrument = None
        
    def _init_otel(self, meter):
        if not self.otel_instrument and meter:
            try:
                self.otel_instrument = meter.create_counter(
                    name=self.name,
                    description=self.documentation
                )
            except Exception as e:
                logger.warning(f"Failed to create OTel counter {self.name}: {e}")

    def labels(self, **kwargs):
        prom_child = self.prom_metric.labels(**kwargs)
        return OTelPrometheusCounterChild(self, prom_child, kwargs)

class OTelPrometheusCounterChild:
    def __init__(self, parent, prom_child, labels_dict):
        self.parent = parent
        self.prom_child = prom_child
        self.labels_dict = labels_dict

    def inc(self, amount=1):
        try:
            self.prom_child.inc(amount)
        except Exception:
            pass
        if self.parent.otel_instrument:
            try:
                self.parent.otel_instrument.add(amount, self.labels_dict)
            except Exception as e:
                logger.debug(f"Failed to add to OTel counter {self.parent.name}: {e}")

    @property
    def _value(self):
        return self.prom_child._value

class OTelPrometheusHistogram:
    def __init__(self, name, documentation, labelnames=(), buckets=None):
        self.name = name
        self.documentation = documentation
        self.labelnames = labelnames
        if buckets:
            self.prom_metric = PromHistogram(name, documentation, labelnames, buckets=buckets)
        else:
            self.prom_metric = PromHistogram(name, documentation, labelnames)
        self.otel_instrument = None

    def _init_otel(self, meter):
        if not self.otel_instrument and meter:
            try:
                self.otel_instrument = meter.create_histogram(
                    name=self.name,
                    description=self.documentation
                )
            except Exception as e:
                logger.warning(f"Failed to create OTel histogram {self.name}: {e}")

    def labels(self, **kwargs):
        prom_child = self.prom_metric.labels(**kwargs)
        return OTelPrometheusHistogramChild(self, prom_child, kwargs)

class OTelPrometheusHistogramChild:
    def __init__(self, parent, prom_child, labels_dict):
        self.parent = parent
        self.prom_child = prom_child
        self.labels_dict = labels_dict

    def observe(self, value):
        try:
            self.prom_child.observe(value)
        except Exception:
            pass
        if self.parent.otel_instrument:
            try:
                self.parent.otel_instrument.record(value, self.labels_dict)
            except Exception as e:
                logger.debug(f"Failed to record to OTel histogram {self.parent.name}: {e}")

    @property
    def _value(self):
        return self.prom_child._value

class OTelPrometheusGauge:
    def __init__(self, name, documentation, labelnames=()):
        self.name = name
        self.documentation = documentation
        self.labelnames = labelnames
        self.prom_metric = PromGauge(name, documentation, labelnames)
        self.otel_instrument = None

    def _init_otel(self, meter):
        if not self.otel_instrument and meter:
            try:
                # OTel Python API >= 1.25.0 supports meter.create_gauge
                self.otel_instrument = meter.create_gauge(
                    name=self.name,
                    description=self.documentation
                )
            except AttributeError:
                # Fallback to UpDownCounter
                try:
                    self.otel_instrument = meter.create_up_down_counter(
                        name=self.name,
                        description=self.documentation
                    )
                except Exception as e:
                    logger.warning(f"Failed to create OTel fallback gauge {self.name}: {e}")
            except Exception as e:
                logger.warning(f"Failed to create OTel gauge {self.name}: {e}")

    def labels(self, **kwargs):
        prom_child = self.prom_metric.labels(**kwargs)
        return OTelPrometheusGaugeChild(self, prom_child, kwargs)

class OTelPrometheusGaugeChild:
    def __init__(self, parent, prom_child, labels_dict):
        self.parent = parent
        self.prom_child = prom_child
        self.labels_dict = labels_dict

    def set(self, value):
        try:
            self.prom_child.set(value)
        except Exception:
            pass
        if self.parent.otel_instrument:
            try:
                if hasattr(self.parent.otel_instrument, "set"):
                    self.parent.otel_instrument.set(value, self.labels_dict)
            except Exception as e:
                logger.debug(f"Failed to set OTel gauge {self.parent.name}: {e}")

    def inc(self, amount=1):
        try:
            self.prom_child.inc(amount)
        except Exception:
            pass
        if self.parent.otel_instrument:
            try:
                if hasattr(self.parent.otel_instrument, "add"):
                    self.parent.otel_instrument.add(amount, self.labels_dict)
                elif hasattr(self.parent.otel_instrument, "set"):
                    new_val = self.prom_child._value.get()
                    self.parent.otel_instrument.set(new_val, self.labels_dict)
            except Exception as e:
                logger.debug(f"Failed to inc OTel gauge {self.parent.name}: {e}")

    def dec(self, amount=1):
        try:
            self.prom_child.dec(amount)
        except Exception:
            pass
        if self.parent.otel_instrument:
            try:
                if hasattr(self.parent.otel_instrument, "add"):
                    self.parent.otel_instrument.add(-amount, self.labels_dict)
                elif hasattr(self.parent.otel_instrument, "set"):
                    new_val = self.prom_child._value.get()
                    self.parent.otel_instrument.set(new_val, self.labels_dict)
            except Exception as e:
                logger.debug(f"Failed to dec OTel gauge {self.parent.name}: {e}")

    @property
    def _value(self):
        return self.prom_child._value

Counter = OTelPrometheusCounter
Histogram = OTelPrometheusHistogram
Gauge = OTelPrometheusGauge

# Counters
aion_messages_total = Counter(
    "aion_messages_total",
    "Total messages processed",
    ["tenant_id", "profile", "role", "finish_reason"],
)

aion_tool_calls_total = Counter(
    "aion_tool_calls_total",
    "Total tool invocations",
    ["tenant_id", "profile", "tool_name", "mcp_server", "status"],  # status: ok | error | blocked
)

# Histograms
aion_turn_duration_seconds = Histogram(
    "aion_turn_duration_seconds",
    "End-to-end turn duration",
    ["tenant_id", "profile"],
    buckets=[0.5, 1, 2, 5, 10, 20, 30, 60, 120],
)

aion_tool_call_duration_seconds = Histogram(
    "aion_tool_call_duration_seconds",
    "Tool execution duration",
    ["tool_name", "mcp_server"],
    buckets=[0.05, 0.1, 0.25, 0.5, 0.75, 1.0, 2.5, 5.0, 10.0, 30.0]
)

aion_session_cache_size_bytes = Gauge(
    "aion_session_cache_size_bytes",
    "Local session file cache footprint",
    ["tenant_id"],
)

# Observability metrics
aion_llm_tokens_total = Counter(
    "aion_llm_tokens_total",
    "LLM token usage",
    ["tenant_id", "profile", "model", "token_type"],  # token_type: prompt | completion | reasoning
)

aion_llm_turn_tokens = Gauge(
    "aion_llm_turn_tokens",
    "LLM tokens used in the last turn",
    ["tenant_id", "profile", "model", "token_type"],  # token_type: prompt | completion | reasoning
)

aion_llm_turn_calls = Gauge(
    "aion_llm_turn_calls",
    "Number of LLM calls made in the last turn",
    ["tenant_id", "profile"],
)

aion_agent_failures_total = Counter(
    "aion_agent_failures_total",
    "Total agent turn failures",
    ["tenant_id", "profile", "error_type"],  # error_type: timeout | error | cancelled | ...
)

aion_mcp_server_healthy = Gauge(
    "aion_mcp_server_healthy",
    "MCP Server health status (1=healthy, 0=unhealthy)",
    ["mcp_server"],
)



_meter_provider = None

def set_meter_provider(provider):
    global _meter_provider
    _meter_provider = provider
    if provider:
        try:
            meter = provider.get_meter("aion-agent")
            for name, obj in list(globals().items()):
                if isinstance(obj, (OTelPrometheusCounter, OTelPrometheusHistogram, OTelPrometheusGauge)):
                    obj._init_otel(meter)
        except Exception as e:
            logger.warning(f"Error initializing OTel instruments: {e}")

