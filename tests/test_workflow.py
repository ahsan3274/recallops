from __future__ import annotations

import copy
import json
import unittest
from pathlib import Path
from types import MethodType

from app.models import EnterpriseEvent
from app.store import LocalStore
from app.workflow import FINANCE_AGENT, RECALL_AGENT, SUPPLY_AGENT, WorkflowEngine

ROOT = Path(__file__).resolve().parents[1]


class WorkflowTests(unittest.TestCase):
    def setUp(self) -> None:
        self.store = LocalStore(ROOT / "seed")
        self.engine = WorkflowEngine(self.store)

    def events(self) -> list[EnterpriseEvent]:
        path = ROOT / "scenarios" / "recall_peanut_01.jsonl"
        return [
            EnterpriseEvent.from_dict(json.loads(line))
            for line in path.read_text(encoding="utf-8").splitlines()
            if line.strip()
        ]

    def test_end_to_end_scenario(self) -> None:
        results = [self.engine.process(event) for event in self.events()]

        product = self.store.find_one("products", "product_id", "PROD-001")
        self.assertEqual(product["listing_status"], "frozen")

        affected = [
            lot
            for lot in self.store.collection("inventory_lots")
            if lot["product_id"] == "PROD-001"
            and lot["lot_code"] in {"L2408", "L2409", "L2410", "L2411"}
        ]
        self.assertTrue(affected)
        self.assertTrue(all(lot["status"] == "quarantined" for lot in affected))

        purchase_orders = self.store.collection("purchase_orders")
        self.assertEqual(len(purchase_orders), 1)
        self.assertEqual(purchase_orders[0]["supplier_id"], "SUP-002")

        claims = self.store.collection("supplier_claims")
        self.assertEqual(len(claims), 1)
        self.assertGreater(claims[0]["claim_amount"], 0)

        invoice = self.store.find_one("supplier_invoices", "invoice_id", "SINV-001")
        self.assertEqual(invoice["status"], "held")
        self.assertEqual(results[-1]["status"], "duplicate_ignored")
        self.assertEqual(len(self.store.collection("processed_events")), len(self.events()) - 1)

    def test_reset_restores_seed_state(self) -> None:
        self.engine.process(self.events()[1])
        self.store.reset()
        product = self.store.find_one("products", "product_id", "PROD-001")
        self.assertEqual(product["listing_status"], "active")
        self.assertEqual(self.store.collection("supplier_claims"), [])

    def test_audit_records_are_structured_and_attributable(self) -> None:
        self.engine.process(self.events()[1])
        required = {
            "audit_id",
            "event_id",
            "scenario_id",
            "occurred_at",
            "actor",
            "action",
            "resource_type",
            "resource_id",
            "outcome",
            "reason",
            "idempotency_key",
            "trace_id",
        }
        audits = self.store.collection("audit_events")
        self.assertTrue(audits)
        self.assertTrue(all(required.issubset(audit) for audit in audits))
        tool_audits = [audit for audit in audits if audit["event_type"] == "tool.executed"]
        self.assertEqual(
            {audit["actor"] for audit in tool_audits},
            {"recall_coordinator", "supply_continuity", "financial_recovery"},
        )

    def test_daily_workflow_count_tracks_recall_events_only(self) -> None:
        self.engine.process(self.events()[0])
        self.assertEqual(self.engine.daily_workflow_count(), 0)
        self.engine.process(self.events()[1])
        self.assertEqual(self.engine.daily_workflow_count(), 1)

    def test_a2a_handoff_audit_is_human_readable_and_idempotent(self) -> None:
        event = self.events()[1]
        self.engine.process(event)
        self.engine.record_handoff(
            event,
            to_agent=SUPPLY_AGENT,
            request_summary="Safe stock is below the seven-day target",
            response_actions=["SafeHarbor Foods selected and PO created"],
            trace_id="trace-supply",
        )
        self.engine.record_handoff(
            event,
            to_agent=SUPPLY_AGENT,
            request_summary="Safe stock is below the seven-day target",
            response_actions=["This duplicate must not be recorded"],
            trace_id="trace-duplicate",
        )

        handoffs = [
            audit
            for audit in self.store.collection("audit_events")
            if audit["resource_type"] == "a2a_agent"
        ]
        self.assertEqual(len(handoffs), 1)
        self.assertEqual(handoffs[0]["from_agent"], "recall_coordinator")
        self.assertEqual(handoffs[0]["to_agent"], "supply_continuity")
        self.assertIn("Recall Coordinator asked Supply Continuity", handoffs[0]["actions"][0])
        self.assertIn("Supply Continuity replied", handoffs[0]["actions"][1])

    def test_finance_resolves_inventory_after_cloud_refresh(self) -> None:
        events = self.events()
        self.engine.transfer_inventory(
            events[0],
            actor=RECALL_AGENT,
            reason="Prepare the authoritative pre-recall inventory state",
        )
        containment = self.engine.contain_recall(
            events[1],
            actor=RECALL_AGENT,
            reason="Contain exact recall before the specialist handoff",
        )
        authoritative = copy.deepcopy(self.store.state)
        self.store.collection("inventory_lots").append(
            {
                "lot_id": "STALE-LATE-LOT",
                "lot_code": "L2411",
                "product_id": "PROD-001",
                "warehouse_id": "WH-CHI",
                "quantity_on_hand": 30,
                "status": "quarantined",
            }
        )

        def refresh_from_authoritative(store: LocalStore) -> None:
            store.state = copy.deepcopy(authoritative)

        self.store.refresh = MethodType(refresh_from_authoritative, self.store)
        result = self.engine.recover_finances(
            event_id=events[1].event_id,
            scenario_id=events[1].scenario_id,
            recall_id=containment["recall_id"],
            purchase_order_id=None,
            actor=FINANCE_AGENT,
            reason="Use only the freshly loaded shared inventory state",
        )

        claim = self.store.find_one(
            "supplier_claims", "supplier_claim_id", result["supplier_claim_id"]
        )
        self.assertEqual(claim["inventory_loss"], 370 * 3.1)


if __name__ == "__main__":
    unittest.main()
