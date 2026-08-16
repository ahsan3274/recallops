from __future__ import annotations

import unittest

from app.telemetry import after_model_call, model_budget_callback, trace_span


class FakeContext:
    def __init__(self):
        self.state: dict[str, int] = {}
        self.agent_name = "recall_coordinator"


class FakeRequest:
    model = "gemini-3.5-flash-lite"


class TelemetryTests(unittest.TestCase):
    def test_model_call_budget_is_enforced(self) -> None:
        context = FakeContext()
        callback = model_budget_callback(2)
        callback(context, FakeRequest())
        after_model_call(context, object())
        callback(context, FakeRequest())
        after_model_call(context, object())

        self.assertEqual(context.state["recallops:model_call_count"], 2)
        with self.assertRaises(RuntimeError):
            callback(context, FakeRequest())

    def test_noop_or_installed_tracer_context_is_safe(self) -> None:
        with trace_span("test.span", {"test.attribute": "value"}):
            pass


if __name__ == "__main__":
    unittest.main()
