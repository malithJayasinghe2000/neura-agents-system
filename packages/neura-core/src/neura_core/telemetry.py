"""OpenTelemetry setup.

One trace spans HTTP request -> graph node -> tool call -> LLM call. The trace ID
is also the ``request_id`` returned to API clients, so a customer quoting an ID
in a complaint leads straight to the run that produced it
(docs/architecture/adr/0007-langfuse-observability.md).

Tracing is optional: with ``OTEL_ENABLED=false`` the no-op tracer is used and
instrumented code paths behave identically.
"""

from __future__ import annotations

from opentelemetry import trace
from opentelemetry.sdk.resources import Resource
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import BatchSpanProcessor
from opentelemetry.trace import Tracer

_configured = False


def configure_telemetry(*, service_name: str, endpoint: str | None, enabled: bool) -> None:
    """Install the tracer provider. Call once, at startup."""
    global _configured
    if _configured or not enabled:
        return

    provider = TracerProvider(resource=Resource.create({"service.name": service_name}))

    if endpoint:
        # Imported lazily so the gRPC exporter is not required when tracing is off.
        from opentelemetry.exporter.otlp.proto.grpc.trace_exporter import (
            OTLPSpanExporter,
        )

        provider.add_span_processor(
            BatchSpanProcessor(OTLPSpanExporter(endpoint=endpoint, insecure=True))
        )

    trace.set_tracer_provider(provider)
    _configured = True


def get_tracer(name: str) -> Tracer:
    return trace.get_tracer(name)


def current_trace_id() -> str | None:
    """The active trace ID as a 32-character hex string, or ``None`` if untraced."""
    span = trace.get_current_span()
    ctx = span.get_span_context()
    if not ctx.is_valid:
        return None
    return format(ctx.trace_id, "032x")
