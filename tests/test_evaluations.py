from __future__ import annotations

import json
import unittest
from pathlib import Path

from app.models import EnterpriseEvent
from app.store import LocalStore
from app.workflow import WorkflowEngine

ROOT = Path(__file__).resolve().parents[1]


class RecallOpsEvaluations(unittest.TestCase):
    def setUp(self) -> None:
        self.store = LocalStore(ROOT / "seed")
        self.engine = WorkflowEngine(self.store)
        self.events = [
            EnterpriseEvent.from_dict(json.loads(line))
            for line in (ROOT / "scenarios" / "recall_peanut_01.jsonl")
            .read_text(encoding="utf-8")
            .splitlines()
            if line.strip()
        ]
        self.recall = next(event for event in self.events if event.event_type == "recall.issued")
        self.receipts = [event for event in self.events if event.event_type == "inventory.received"]

    def test_evaluation_manifest_has_every_required_case(self) -> None:
        manifest = json.loads(
            (ROOT / "evals" / "recallops_cases.json").read_text(encoding="utf-8")
        )
        self.assertEqual(
            {case["id"] for case in manifest["cases"]},
            {
                "normal_exact_recall",
                "ambiguous_private_label",
                "duplicate_event",
                "late_inventory_arrival",
                "expired_supplier_certification",
                "approval_required_financial_actions",
            },
        )

    def test_normal_exact_recall(self) -> None:
        result = self.engine.process(self.recall)
        self.assertEqual(result["status"], "completed")
        self.assertEqual(
            self.store.find_one("products", "product_id", "PROD-001")["listing_status"],
            "frozen",
        )
        self.assertGreater(result["metrics"]["quarantined_units"], 0)
        self.assertGreater(result["metrics"]["affected_orders"], 0)

    def test_ambiguous_match_requires_approval(self) -> None:
        payload = dict(self.recall.payload)
        payload.update({"recall_id": "REC-AMB", "product_id": "PRIVATE-LABEL-UNKNOWN"})
        result = self.engine.process(
            EnterpriseEvent(
                event_id="evt-ambiguous-eval",
                event_type="recall.issued",
                occurred_at=self.recall.occurred_at,
                source="evaluation",
                scenario_id="ambiguous-eval",
                payload=payload,
            )
        )
        self.assertEqual(result["status"], "approval_required")
        self.assertEqual(self.store.collection("active_recalls"), [])
        self.assertEqual(
            self.store.collection("approval_requests")[0]["type"],
            "ambiguous_recall_match",
        )

    def test_duplicate_event_is_ignored(self) -> None:
        self.engine.process(self.recall)
        first = self.engine.process(self.receipts[0])
        duplicate = self.engine.process(self.receipts[1])
        lot = self.store.find_one("inventory_lots", "lot_id", "LOT-LATE-001")
        self.assertEqual(first["status"], "processed")
        self.assertEqual(duplicate["status"], "duplicate_ignored")
        self.assertEqual(lot["quantity_on_hand"], 30)

    def test_late_inventory_arrival_is_quarantined(self) -> None:
        self.engine.process(self.recall)
        self.engine.process(self.receipts[0])
        lot = self.store.find_one("inventory_lots", "lot_id", "LOT-LATE-001")
        self.assertEqual(lot["status"], "quarantined")
        task = self.store.find_one("warehouse_tasks", "lot_id", "LOT-LATE-001")
        self.assertEqual(task["type"], "quarantine_late_arrival")

    def test_expired_supplier_certification_is_disqualified(self) -> None:
        self.engine.process(self.recall)
        purchase_order = self.store.collection("purchase_orders")[0]
        expired_offer = self.store.find_one("supplier_offers", "offer_id", "OFFER-002")
        self.assertEqual(expired_offer["certificate_status"], "expired")
        self.assertNotEqual(purchase_order["supplier_id"], expired_offer["supplier_id"])
        self.assertEqual(purchase_order["supplier_id"], "SUP-002")

    def test_high_value_po_and_claim_require_approval(self) -> None:
        product = self.store.find_one("products", "product_id", "PROD-001")
        contract = self.store.find_one("supplier_contracts", "supplier_id", "SUP-001")
        product["po_auto_approval_limit"] = 1.0
        contract["claim_auto_approval_limit"] = 1.0

        self.engine.process(self.recall)
        approvals = self.store.collection("approval_requests")
        self.assertIn("purchase_order", {approval["type"] for approval in approvals})
        self.assertIn("supplier_claim", {approval["type"] for approval in approvals})
        self.assertEqual(self.store.collection("purchase_orders"), [])
        self.assertEqual(self.store.collection("supplier_claims")[0]["status"], "approval_required")


if __name__ == "__main__":
    unittest.main()
