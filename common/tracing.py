"""
common/tracing.py — Opt-in OpenTelemetry setup shared by monitor.py and the orchestrator.

Call `setup_tracing()` once at process start (BEFORE creating any AIProjectClient) to get:
  * GenAI spans from the Foundry SDK (AIProjectInstrumentor) — model calls, tool calls, tokens
  * export to Application Insights (configure_azure_monitor)
  * a tracer for our own business spans (`pipeline_span`) carrying customer/repo KPIs

Business KPIs are attached as span attributes with the `bc.` prefix so they can be queried
in Log Analytics via customDimensions — see monitoring/queries.kql.
"""

from __future__ import annotations

import os
from contextlib import contextmanager

_TRACING_ENABLED = False


def setup_tracing(connection_string: str | None = None, live_metrics: bool = False) -> bool:
    """Enable GenAI tracing + Azure Monitor export. Returns True when active."""
    global _TRACING_ENABLED
    connection_string = connection_string or os.getenv("APPLICATIONINSIGHTS_CONNECTION_STRING", "")
    if not connection_string:
        print("[TRACE] APPLICATIONINSIGHTS_CONNECTION_STRING not set — tracing disabled")
        return False

    # These must be set before the Foundry SDK is imported for message content to be captured.
    os.environ.setdefault("AZURE_EXPERIMENTAL_ENABLE_GENAI_TRACING", "true")
    os.environ.setdefault("OTEL_INSTRUMENTATION_GENAI_CAPTURE_MESSAGE_CONTENT", "true")
    os.environ.setdefault("OTEL_SERVICE_NAME", "bc-deployment-analyzer")

    from azure.monitor.opentelemetry import configure_azure_monitor

    configure_azure_monitor(connection_string=connection_string, enable_live_metrics=live_metrics)

    from azure.ai.projects.telemetry import AIProjectInstrumentor

    AIProjectInstrumentor().instrument()
    _TRACING_ENABLED = True
    print("[TRACE] GenAI tracing → Application Insights enabled")
    return True


def tracing_enabled() -> bool:
    return _TRACING_ENABLED


def get_tracer(name: str = "bc-deployment-analyzer"):
    from opentelemetry import trace

    return trace.get_tracer(name)


@contextmanager
def pipeline_span(name: str, **attributes):
    """
    Business-level span. Works even when tracing is disabled (the OTel no-op tracer is used),
    so orchestration code never has to check whether monitoring is switched on.
    """
    tracer = get_tracer()
    with tracer.start_as_current_span(name) as span:
        for key, value in attributes.items():
            if value is not None:
                span.set_attribute(f"bc.{key}", value)
        yield span


def record_kpis(span, **kpis) -> None:
    """Attach numeric KPIs (tokens, docs updated, mismatches…) to the current span."""
    for key, value in kpis.items():
        if value is not None:
            span.set_attribute(f"bc.{key}", value)


def flush() -> None:
    """Force export before a short-lived process exits (CI runs, scheduled jobs)."""
    if not _TRACING_ENABLED:
        return
    try:
        from opentelemetry import trace

        provider = trace.get_tracer_provider()
        if hasattr(provider, "force_flush"):
            provider.force_flush()
    except Exception as exc:  # pragma: no cover — best effort
        print(f"[TRACE] flush failed: {exc}")
