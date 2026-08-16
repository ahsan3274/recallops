from __future__ import annotations

import json
import unittest
from pathlib import Path

from app.agent_tools import build_toolsets
from app.models import EnterpriseEvent
from app.store import LocalStore
from app.workflow import FINANCE_AGENT, WorkflowEngine

ROOT = Path(__file__).resolve().parents[1]


class AgentToolTests(unittest.TestCase):
    def setUp(self) -> None:
        self.store = LocalStore(ROOT / "seed")
        self.engine = WorkflowEngine(self.store)
        self.recall, self.supply, self.finance = build_toolsets(self.engine)
        events = [
            EnterpriseEvent.from_dict(json.loads(line))
            for line in (ROOT / "scenarios" / "recall_peanut_01.jsonl")
            .read_text(encoding="utf-8")
            .splitlines()
            if line.strip()
        ]
        self.recall_event = next(event for event in events if event.event_type == "recall.issued")
        self.transfer_event = next(
            event for event in events if event.event_type == "inventory.transferred"
        )
        self.receipt_event = next(
            event for event in events if event.event_type == "inventory.received"
        )

    def test_typed_tools_enforce_identity_and_are_idempotent(self) -> None:
        payload = self.recall_event.payload
        result = self.recall.contain_recall(
            event_id=self.recall_event.event_id,
            occurred_at=self.recall_event.occurred_at,
            source=self.recall_event.source,
            scenario_id=self.recall_event.scenario_id,
            recall_id=payload["recall_id"],
            recall_number=payload["recall_number"],
            product_id=payload["product_id"],
            lot_codes=payload["lot_codes"],
            classification=payload["classification"],
            reason=payload["reason"],
        )
        duplicate = self.recall.contain_recall(
            event_id=self.recall_event.event_id,
            occurred_at=self.recall_event.occurred_at,
            source=self.recall_event.source,
            scenario_id=self.recall_event.scenario_id,
            recall_id=payload["recall_id"],
            recall_number=payload["recall_number"],
            product_id=payload["product_id"],
            lot_codes=payload["lot_codes"],
            classification=payload["classification"],
            reason=payload["reason"],
        )

        self.assertEqual(result["status"], "contained")
        self.assertEqual(duplicate["tool_status"], "duplicate_ignored")
        self.assertEqual(len(self.store.collection("active_recalls")), 1)
        execution = self.store.collection("tool_executions")[0]
        self.assertEqual(execution["actor"], "recall_coordinator")

        with self.assertRaises(PermissionError):
            self.engine.recover_finances(
                event_id="evt-forbidden",
                scenario_id=self.recall_event.scenario_id,
                recall_id=payload["recall_id"],
                purchase_order_id=None,
                actor="supply_continuity",
                reason="Attempt cross-domain mutation",
            )

    def test_ambiguous_match_creates_approval_without_mutating_products(self) -> None:
        result = self.recall.contain_recall(
            event_id="evt-ambiguous",
            occurred_at=self.recall_event.occurred_at,
            source="test",
            scenario_id="ambiguous-test",
            recall_id="REC-AMB",
            recall_number="AMB-1",
            product_id="UNKNOWN",
            lot_codes=["UNKNOWN"],
            classification="Class II",
            reason="Private-label description is ambiguous",
        )

        self.assertEqual(result["status"], "approval_required")
        self.assertEqual(len(self.store.collection("active_recalls")), 0)
        approval = self.store.collection("approval_requests")[0]
        self.assertEqual(approval["type"], "ambiguous_recall_match")

    def test_finance_tool_cannot_accept_model_supplied_identity(self) -> None:
        parameters = self.finance.recover_finances.__annotations__
        self.assertNotIn("actor", parameters)
        self.assertEqual(FINANCE_AGENT, "financial_recovery")

    def test_recall_inventory_event_adapters_use_validated_tools(self) -> None:
        transfer = self.transfer_event.payload
        transferred = self.recall.transfer_inventory(
            event_id=self.transfer_event.event_id,
            occurred_at=self.transfer_event.occurred_at,
            source=self.transfer_event.source,
            scenario_id=self.transfer_event.scenario_id,
            source_lot_id=transfer["source_lot_id"],
            destination_lot_id=transfer["destination_lot_id"],
            destination_warehouse_id=transfer["destination_warehouse_id"],
            quantity=transfer["quantity"],
        )
        self.assertEqual(transferred["status"], "processed")

        recall = self.recall_event.payload
        self.recall.contain_recall(
            event_id=self.recall_event.event_id,
            occurred_at=self.recall_event.occurred_at,
            source=self.recall_event.source,
            scenario_id=self.recall_event.scenario_id,
            recall_id=recall["recall_id"],
            recall_number=recall["recall_number"],
            product_id=recall["product_id"],
            lot_codes=recall["lot_codes"],
            classification=recall["classification"],
            reason=recall["reason"],
        )
        receipt = self.receipt_event.payload
        received = self.recall.receive_inventory(
            event_id=self.receipt_event.event_id,
            occurred_at=self.receipt_event.occurred_at,
            source=self.receipt_event.source,
            scenario_id=self.receipt_event.scenario_id,
            lot_id=receipt["lot_id"],
            lot_code=receipt["lot_code"],
            product_id=receipt["product_id"],
            warehouse_id=receipt["warehouse_id"],
            quantity=receipt["quantity"],
        )
        self.assertEqual(received["status"], "processed")
        late_lot = self.store.find_one("inventory_lots", "lot_id", receipt["lot_id"])
        self.assertEqual(late_lot["status"], "quarantined")


if __name__ == "__main__":
    unittest.main()
