"""Optional OpenTelemetry instrumentation with direct Cloud Trace export."""

from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager
from contextvars import ContextVar
from typing import Any

_model_span_stack: ContextVar[tuple[Any, ...]] = ContextVar("model_span_stack", default=())


def configure_cloud_trace(enabled: bool, project: str, service_name: str) -> None:
    """Configure direct Cloud Trace export only when explicitly enabled."""

    if not enabled:
        return
    try:
        from opentelemetry import trace
        from opentelemetry.exporter.cloud_trace import CloudTraceSpanExporter
        from opentelemetry.sdk.resources import SERVICE_NAME, Resource
        from opentelemetry.sdk.trace import TracerProvider
        from opentelemetry.sdk.trace.export import BatchSpanProcessor
    except ImportError as exc:
        raise RuntimeError(
            "Cloud Trace requires the OpenTelemetry packages in the google extra"
        ) from exc
    provider = TracerProvider(resource=Resource.create({SERVICE_NAME: service_name}))
    provider.add_span_processor(BatchSpanProcessor(CloudTraceSpanExporter(project_id=project)))
    trace.set_tracer_provider(provider)


def _tracer() -> Any | None:
    try:
        from opentelemetry import trace
    except ImportError:
        return None
    return trace.get_tracer("recallops")


@contextmanager
def trace_span(name: str, attributes: dict[str, Any] | None = None) -> Iterator[Any | None]:
    tracer = _tracer()
    if tracer is None:
        yield None
        return
    with tracer.start_as_current_span(name, attributes=attributes or {}) as span:
        yield span


def current_trace_id() -> str | None:
    try:
        from opentelemetry import trace
    except ImportError:
        return None
    context = trace.get_current_span().get_span_context()
    if not context.is_valid:
        return None
    return format(context.trace_id, "032x")


def before_model_call(callback_context: Any, llm_request: Any) -> None:
    """ADK callback that opens one span around an actual model invocation."""

    tracer = _tracer()
    if tracer is None:
        return None
    manager = tracer.start_as_current_span(
        "model.call",
        attributes={
            "gen_ai.system": "google_gemini",
            "gen_ai.request.model": str(getattr(llm_request, "model", "unknown")),
            "recallops.agent": str(getattr(callback_context, "agent_name", "unknown")),
        },
    )
    manager.__enter__()
    _model_span_stack.set((*_model_span_stack.get(), manager))
    return None


def model_budget_callback(max_calls: int) -> Any:
    """Create an ADK before-model callback enforcing the workflow-wide call ceiling."""

    def callback(callback_context: Any, llm_request: Any) -> None:
        state = callback_context.state
        count = int(state.get("recallops:model_call_count", 0))
        if count >= max_calls:
            raise RuntimeError(f"Model call limit of {max_calls} exceeded")
        state["recallops:model_call_count"] = count + 1
        return before_model_call(callback_context, llm_request)

    return callback


def after_model_call(callback_context: Any, llm_response: Any) -> None:
    """ADK callback that closes the span opened immediately before the model call."""

    stack = _model_span_stack.get()
    if not stack:
        return None
    manager = stack[-1]
    _model_span_stack.set(stack[:-1])
    manager.__exit__(None, None, None)
    return None
