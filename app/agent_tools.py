"""Typed ADK tool adapters around deterministic RecallOps policy operations.

The model supplies business inputs only. Agent identity is fixed by each adapter,
so a prompt cannot borrow another department's mutation permissions.
"""

from __future__ import annotations

from app.models import EnterpriseEvent
from app.workflow import FINANCE_AGENT, RECALL_AGENT, SUPPLY_AGENT, WorkflowEngine


class RecallCoordinatorTools:
    def __init__(self, engine: WorkflowEngine):
        self.engine = engine

    def contain_recall(
        self,
        event_id: str,
        occurred_at: str,
        source: str,
        scenario_id: str,
        recall_id: str,
        recall_number: str,
        product_id: str,
        lot_codes: list[str],
        classification: str,
        reason: str,
    ) -> dict:
        """Contain an exact recall match; ambiguous product IDs create an approval request."""

        event = EnterpriseEvent(
            event_id=event_id,
            event_type="recall.issued",
            occurred_at=occurred_at,
            source=source,
            scenario_id=scenario_id,
            payload={
                "recall_id": recall_id,
                "recall_number": recall_number,
                "product_id": product_id,
                "lot_codes": lot_codes,
                "classification": classification,
                "reason": reason,
            },
        )
        return self.engine.contain_recall(
            event,
            actor=RECALL_AGENT,
            reason="ADK requested deterministic containment for an exact identifier match",
        )

    def receive_inventory(
        self,
        event_id: str,
        occurred_at: str,
        source: str,
        scenario_id: str,
        lot_id: str,
        lot_code: str,
        product_id: str,
        warehouse_id: str,
        quantity: int,
    ) -> dict:
        """Receive stock and quarantine it immediately when an active recall matches."""

        event = EnterpriseEvent(
            event_id=event_id,
            event_type="inventory.received",
            occurred_at=occurred_at,
            source=source,
            scenario_id=scenario_id,
            payload={
                "lot_id": lot_id,
                "lot_code": lot_code,
                "product_id": product_id,
                "warehouse_id": warehouse_id,
                "quantity": quantity,
            },
        )
        return self.engine.receive_inventory(
            event,
            actor=RECALL_AGENT,
            reason="ADK requested deterministic processing of an inventory receipt",
        )

    def transfer_inventory(
        self,
        event_id: str,
        occurred_at: str,
        source: str,
        scenario_id: str,
        source_lot_id: str,
        destination_lot_id: str,
        destination_warehouse_id: str,
        quantity: int,
    ) -> dict:
        """Apply a validated inventory transfer before later recall containment."""

        event = EnterpriseEvent(
            event_id=event_id,
            event_type="inventory.transferred",
            occurred_at=occurred_at,
            source=source,
            scenario_id=scenario_id,
            payload={
                "source_lot_id": source_lot_id,
                "destination_lot_id": destination_lot_id,
                "destination_warehouse_id": destination_warehouse_id,
                "quantity": quantity,
            },
        )
        return self.engine.transfer_inventory(
            event,
            actor=RECALL_AGENT,
            reason="ADK requested deterministic processing of an inventory transfer",
        )


class SupplyContinuityTools:
    def __init__(self, engine: WorkflowEngine):
        self.engine = engine

    def restore_supply(
        self, event_id: str, scenario_id: str, recall_id: str, reason: str
    ) -> dict:
        """Select a certified replacement and create only a policy-bounded purchase order."""

        return self.engine.restore_supply(
            event_id=event_id,
            scenario_id=scenario_id,
            recall_id=recall_id,
            actor=SUPPLY_AGENT,
            reason=reason,
        )


class FinancialRecoveryTools:
    def __init__(self, engine: WorkflowEngine):
        self.engine = engine

    def recover_finances(
        self,
        event_id: str,
        scenario_id: str,
        recall_id: str,
        reason: str,
        purchase_order_id: str = "",
    ) -> dict:
        """Calculate contract-backed loss, hold linked invoices, and create a bounded claim."""

        return self.engine.recover_finances(
            event_id=event_id,
            scenario_id=scenario_id,
            recall_id=recall_id,
            purchase_order_id=purchase_order_id or None,
            actor=FINANCE_AGENT,
            reason=reason,
        )


def build_toolsets(
    engine: WorkflowEngine,
) -> tuple[RecallCoordinatorTools, SupplyContinuityTools, FinancialRecoveryTools]:
    """Create the three department-scoped tool adapters for an ADK runtime."""

    return (
        RecallCoordinatorTools(engine),
        SupplyContinuityTools(engine),
        FinancialRecoveryTools(engine),
    )
