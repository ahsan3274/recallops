from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

from app.models import EnterpriseEvent
from app.store import StateStore
from app.telemetry import current_trace_id, trace_span

RECALL_AGENT = "recall_coordinator"
SUPPLY_AGENT = "supply_continuity"
FINANCE_AGENT = "financial_recovery"

TOOL_PERMISSIONS = {
    "contain_recall": RECALL_AGENT,
    "receive_inventory": RECALL_AGENT,
    "transfer_inventory": RECALL_AGENT,
    "restore_supply": SUPPLY_AGENT,
    "recover_finances": FINANCE_AGENT,
}


def utc_now() -> str:
    return datetime.now(UTC).isoformat()


class WorkflowEngine:
    """Deterministic reference implementation for the three business agents.

    These methods become validated ADK tools. Policy checks remain here even
    after Gemini takes over routing.
    """

    def __init__(self, store: StateStore):
        self.store = store

    def process(self, event: EnterpriseEvent) -> dict[str, Any]:
        self.store.refresh()
        if self.store.has_processed_event(event.event_id):
            return {
                "event_id": event.event_id,
                "status": "duplicate_ignored",
                "actions": [],
            }

        handlers = {
            "inventory.received": lambda current: self.receive_inventory(
                current, actor=RECALL_AGENT, reason="Process enterprise inventory receipt"
            ),
            "inventory.transferred": lambda current: self.transfer_inventory(
                current, actor=RECALL_AGENT, reason="Process enterprise inventory transfer"
            ),
            "recall.issued": self._orchestrate_recall,
        }
        handler = handlers.get(event.event_type)
        if handler is None:
            result = {"status": "ignored", "actions": [f"Unknown event: {event.event_type}"]}
        else:
            with trace_span(
                "workflow.event",
                {
                    "recallops.event_id": event.event_id,
                    "recallops.event_type": event.event_type,
                    "recallops.scenario_id": event.scenario_id,
                },
            ):
                result = handler(event)

        self.store.mark_processed_event(
            event.event_id, event.scenario_id, event.event_type, utc_now()
        )

        audit = {
            "audit_id": f"AUDIT-{event.event_id}-event",
            "event_id": event.event_id,
            "event_type": event.event_type,
            "scenario_id": event.scenario_id,
            "occurred_at": utc_now(),
            "processed_at": utc_now(),
            "actor": "workflow_engine",
            "action": "process_event",
            "resource_type": "enterprise_event",
            "resource_id": event.event_id,
            "outcome": result["status"],
            "reason": f"Dispatch {event.event_type}",
            "idempotency_key": event.event_id,
            "trace_id": current_trace_id(),
            "status": result["status"],
            "actions": result.get("actions", []),
        }
        self.store.collection("audit_events").append(audit)
        self.store.flush()
        return {"event_id": event.event_id, **result}

    def record_agent_processing(
        self, event: EnterpriseEvent, result: dict[str, Any]
    ) -> None:
        """Finalize idempotency and audit state after an ADK-routed event completes."""

        self.store.refresh()
        if self.store.has_processed_event(event.event_id):
            return
        self.store.mark_processed_event(
            event.event_id, event.scenario_id, event.event_type, utc_now()
        )
        now = utc_now()
        self.store.collection("audit_events").append(
            {
                "audit_id": f"AUDIT-{event.event_id}-adk",
                "event_id": event.event_id,
                "event_type": event.event_type,
                "scenario_id": event.scenario_id,
                "occurred_at": now,
                "processed_at": now,
                "actor": RECALL_AGENT,
                "action": "adk_process_event",
                "resource_type": "enterprise_event",
                "resource_id": event.event_id,
                "outcome": result.get("status", "completed"),
                "reason": "Google ADK routed the enterprise event",
                "idempotency_key": event.event_id,
                "trace_id": current_trace_id(),
                "status": result.get("status", "completed"),
                "actions": [],
            }
        )
        self.store.flush()

    def daily_workflow_count(self) -> int:
        """Count today's recall workflows for the application-level cost guard."""

        self.store.refresh()
        today = datetime.now(UTC).date().isoformat()
        return sum(
            item.get("event_type") == "recall.issued"
            and str(item.get("processed_at", "")).startswith(today)
            for item in self.store.collection("processed_events")
        )

    def record_handoff(
        self,
        event: EnterpriseEvent,
        *,
        to_agent: str,
        request_summary: str,
        response_actions: list[str],
        trace_id: str | None,
    ) -> None:
        """Record one completed Registry/A2A exchange in judge-readable form."""

        if to_agent not in {SUPPLY_AGENT, FINANCE_AGENT}:
            raise ValueError(f"Unsupported specialist handoff target: {to_agent}")
        self.store.refresh()
        idempotency_key = f"{event.event_id}:handoff:{to_agent}"
        audit_id = f"AUDIT-{idempotency_key}"
        if self.store.find_one("audit_events", "audit_id", audit_id) is not None:
            return
        now = utc_now()
        target_label = {
            SUPPLY_AGENT: "Supply Continuity",
            FINANCE_AGENT: "Financial Recovery",
        }[to_agent]
        self.store.collection("audit_events").append(
            {
                "audit_id": audit_id,
                "event_id": event.event_id,
                "event_type": "agent.handoff",
                "scenario_id": event.scenario_id,
                "occurred_at": now,
                "processed_at": now,
                "actor": RECALL_AGENT,
                "action": f"handoff_{to_agent}",
                "resource_type": "a2a_agent",
                "resource_id": to_agent,
                "outcome": "completed",
                "reason": request_summary,
                "idempotency_key": idempotency_key,
                "trace_id": trace_id,
                "status": "completed",
                "from_agent": RECALL_AGENT,
                "to_agent": to_agent,
                "actions": [
                    f"Recall Coordinator asked {target_label}: {request_summary}",
                    *[f"{target_label} replied: {action}" for action in response_actions],
                ],
            }
        )
        self.store.flush()

    def _execute_tool(
        self,
        *,
        tool_name: str,
        event_id: str,
        scenario_id: str,
        actor: str,
        reason: str,
        operation: Any,
    ) -> dict[str, Any]:
        """Run one policy-owned mutation once and attribute it to a fixed agent identity."""

        expected_actor = TOOL_PERMISSIONS[tool_name]
        if actor != expected_actor:
            raise PermissionError(f"{actor} is not permitted to execute {tool_name}")
        if not event_id or not scenario_id or not reason.strip():
            raise ValueError("Tool calls require event_id, scenario_id, and reason")

        self.store.refresh()
        idempotency_key = f"{event_id}:{tool_name}"
        previous = self.store.find_one("tool_executions", "idempotency_key", idempotency_key)
        if previous is not None:
            return {**previous["result"], "tool_status": "duplicate_ignored"}

        with trace_span(
            "tool.call",
            {
                "recallops.tool": tool_name,
                "recallops.actor": actor,
                "recallops.event_id": event_id,
                "recallops.scenario_id": scenario_id,
            },
        ):
            result = operation()
            execution = {
                "idempotency_key": idempotency_key,
                "event_id": event_id,
                "scenario_id": scenario_id,
                "tool_name": tool_name,
                "actor": actor,
                "reason": reason,
                "executed_at": utc_now(),
                "trace_id": current_trace_id(),
                "result": result,
            }
            self.store.collection("tool_executions").append(execution)
            self.store.collection("audit_events").append(
                {
                    "audit_id": f"AUDIT-{idempotency_key}",
                    "event_id": event_id,
                    "scenario_id": scenario_id,
                    "event_type": "tool.executed",
                    "occurred_at": execution["executed_at"],
                    "processed_at": execution["executed_at"],
                    "actor": actor,
                    "action": tool_name,
                    "resource_type": "workflow_tool",
                    "resource_id": idempotency_key,
                    "outcome": result.get("status", "completed"),
                    "reason": reason,
                    "idempotency_key": idempotency_key,
                    "trace_id": execution["trace_id"],
                    "status": result.get("status", "completed"),
                    "tool_name": tool_name,
                    "actions": result.get("actions", []),
                }
            )
        self.store.flush()
        return result

    def receive_inventory(
        self, event: EnterpriseEvent, *, actor: str, reason: str
    ) -> dict[str, Any]:
        return self._execute_tool(
            tool_name="receive_inventory",
            event_id=event.event_id,
            scenario_id=event.scenario_id,
            actor=actor,
            reason=reason,
            operation=lambda: self._inventory_received(event),
        )

    def transfer_inventory(
        self, event: EnterpriseEvent, *, actor: str, reason: str
    ) -> dict[str, Any]:
        return self._execute_tool(
            tool_name="transfer_inventory",
            event_id=event.event_id,
            scenario_id=event.scenario_id,
            actor=actor,
            reason=reason,
            operation=lambda: self._inventory_transferred(event),
        )

    def _inventory_received(self, event: EnterpriseEvent) -> dict[str, Any]:
        payload = event.payload
        required = {"lot_id", "lot_code", "product_id", "warehouse_id", "quantity"}
        missing = required.difference(payload)
        if missing:
            raise ValueError(f"Missing inventory fields: {', '.join(sorted(missing))}")

        existing = self.store.find_one("inventory_lots", "lot_id", payload["lot_id"])
        if existing:
            existing["quantity_on_hand"] += int(payload["quantity"])
            lot = existing
        else:
            lot = {
                "lot_id": payload["lot_id"],
                "lot_code": payload["lot_code"],
                "product_id": payload["product_id"],
                "warehouse_id": payload["warehouse_id"],
                "quantity_on_hand": int(payload["quantity"]),
                "status": "available",
            }
            self.store.collection("inventory_lots").append(lot)

        actions = [f"Received {payload['quantity']} units into {payload['warehouse_id']}"]
        active_recall = self._matching_active_recall(payload["product_id"], payload["lot_code"])
        if active_recall:
            lot["status"] = "quarantined"
            actions.append(
                f"Recall Coordinator quarantined late-arriving lot {payload['lot_code']}"
            )
            self.store.collection("warehouse_tasks").append(
                {
                    "task_id": f"TASK-{event.event_id}",
                    "type": "quarantine_late_arrival",
                    "warehouse_id": payload["warehouse_id"],
                    "lot_id": payload["lot_id"],
                    "status": "created",
                    "recall_id": active_recall["recall_id"],
                }
            )
        return {"status": "processed", "actions": actions}

    def _inventory_transferred(self, event: EnterpriseEvent) -> dict[str, Any]:
        payload = event.payload
        source = self.store.find_one("inventory_lots", "lot_id", payload["source_lot_id"])
        if source is None:
            raise ValueError(f"Unknown source lot {payload['source_lot_id']}")
        quantity = int(payload["quantity"])
        if quantity <= 0 or source["quantity_on_hand"] < quantity:
            raise ValueError("Invalid transfer quantity")
        source["quantity_on_hand"] -= quantity
        destination_id = payload["destination_lot_id"]
        destination = self.store.find_one("inventory_lots", "lot_id", destination_id)
        if destination:
            destination["quantity_on_hand"] += quantity
        else:
            destination = {
                "lot_id": destination_id,
                "lot_code": source["lot_code"],
                "product_id": source["product_id"],
                "warehouse_id": payload["destination_warehouse_id"],
                "quantity_on_hand": quantity,
                "status": source["status"],
            }
            self.store.collection("inventory_lots").append(destination)
        return {
            "status": "processed",
            "actions": [
                f"Transferred {quantity} units from {source['warehouse_id']} "
                f"to {destination['warehouse_id']}"
            ],
        }

    def contain_recall(
        self, event: EnterpriseEvent, *, actor: str, reason: str
    ) -> dict[str, Any]:
        return self._execute_tool(
            tool_name="contain_recall",
            event_id=event.event_id,
            scenario_id=event.scenario_id,
            actor=actor,
            reason=reason,
            operation=lambda: self._contain_recall(event),
        )

    def _contain_recall(self, event: EnterpriseEvent) -> dict[str, Any]:
        payload = event.payload
        required = {
            "recall_id",
            "recall_number",
            "product_id",
            "lot_codes",
            "classification",
            "reason",
        }
        missing = required.difference(payload)
        if missing:
            raise ValueError(f"Missing recall fields: {', '.join(sorted(missing))}")
        product = self.store.find_one("products", "product_id", payload["product_id"])
        if product is None:
            self.store.collection("approval_requests").append(
                {
                    "approval_id": f"APPROVAL-MATCH-{payload['recall_id']}",
                    "type": "ambiguous_recall_match",
                    "status": "pending",
                    "event_id": event.event_id,
                    "scenario_id": event.scenario_id,
                }
            )
            return {
                "status": "approval_required",
                "actions": ["Recall product could not be matched confidently"],
                "requires_supply": False,
                "requires_finance": False,
            }

        recall = {
            "recall_id": payload["recall_id"],
            "recall_number": payload["recall_number"],
            "product_id": product["product_id"],
            "lot_codes": list(payload["lot_codes"]),
            "classification": payload["classification"],
            "reason": payload["reason"],
            "status": "active",
            "opened_at": event.occurred_at,
        }
        self.store.collection("active_recalls").append(recall)

        product["listing_status"] = "frozen"
        quarantined = self._quarantine_matching_lots(recall)
        impacted_orders = self._affected_orders(recall)

        for order in impacted_orders:
            self.store.collection("notifications").append(
                {
                    "notification_id": f"NOTICE-{order['order_id']}",
                    "order_id": order["order_id"],
                    "customer_id": order["customer_id"],
                    "channel": "email",
                    "template": "food-recall-v1",
                    "status": "prepared",
                }
            )

        self.store.collection("warehouse_tasks").extend(
            {
                "task_id": f"TASK-{lot['lot_id']}",
                "type": "quarantine",
                "warehouse_id": lot["warehouse_id"],
                "lot_id": lot["lot_id"],
                "status": "created",
                "recall_id": recall["recall_id"],
            }
            for lot in quarantined
        )

        actions = [
            f"Recall Coordinator froze listing {product['sku']}",
            f"Quarantined {sum(lot['quantity_on_hand'] for lot in quarantined)} units",
            f"Prepared {len(impacted_orders)} customer notifications",
        ]
        safe_stock = self._safe_stock(product["product_id"])
        target_stock = int(product["daily_demand"] * 7)
        return {
            "status": "contained",
            "actions": actions,
            "recall_id": recall["recall_id"],
            "product_id": product["product_id"],
            "requires_supply": safe_stock < target_stock,
            "requires_finance": bool(quarantined or impacted_orders),
            "metrics": {
                "quarantined_lots": len(quarantined),
                "quarantined_units": sum(lot["quantity_on_hand"] for lot in quarantined),
                "affected_orders": len(impacted_orders),
            },
        }

    def _orchestrate_recall(self, event: EnterpriseEvent) -> dict[str, Any]:
        containment = self.contain_recall(
            event, actor=RECALL_AGENT, reason="Contain an exact product and lot recall match"
        )
        if containment["status"] == "approval_required":
            return containment

        supply = {"actions": []}
        if containment["requires_supply"]:
            with trace_span(
                "agent.handoff",
                {"recallops.from_agent": RECALL_AGENT, "recallops.to_agent": SUPPLY_AGENT},
            ):
                supply = self.restore_supply(
                    event_id=event.event_id,
                    scenario_id=event.scenario_id,
                    recall_id=containment["recall_id"],
                    actor=SUPPLY_AGENT,
                    reason="Safe stock is below the seven-day target",
                )

        finance = {"actions": []}
        if containment["requires_finance"]:
            with trace_span(
                "agent.handoff",
                {"recallops.from_agent": RECALL_AGENT, "recallops.to_agent": FINANCE_AGENT},
            ):
                finance = self.recover_finances(
                    event_id=event.event_id,
                    scenario_id=event.scenario_id,
                    recall_id=containment["recall_id"],
                    purchase_order_id=supply.get("purchase_order_id"),
                    actor=FINANCE_AGENT,
                    reason="Contained inventory or fulfilled orders created recoverable loss",
                )

        metrics = dict(containment["metrics"])
        metrics["purchase_order_id"] = supply.get("purchase_order_id")
        metrics["supplier_claim_id"] = finance.get("supplier_claim_id")
        return {
            "status": "completed",
            "actions": [*containment["actions"], *supply["actions"], *finance["actions"]],
            "metrics": metrics,
        }

    def _matching_active_recall(self, product_id: str, lot_code: str) -> dict[str, Any] | None:
        return next(
            (
                recall
                for recall in self.store.collection("active_recalls")
                if recall["status"] == "active"
                and recall["product_id"] == product_id
                and lot_code in recall["lot_codes"]
            ),
            None,
        )

    def _quarantine_matching_lots(self, recall: dict[str, Any]) -> list[dict[str, Any]]:
        affected = []
        for lot in self.store.collection("inventory_lots"):
            if lot["product_id"] == recall["product_id"] and lot["lot_code"] in recall["lot_codes"]:
                lot["status"] = "quarantined"
                affected.append(lot)
        return affected

    def _affected_orders(self, recall: dict[str, Any]) -> list[dict[str, Any]]:
        affected = []
        for order in self.store.collection("orders"):
            if any(
                line["product_id"] == recall["product_id"]
                and line["lot_code"] in recall["lot_codes"]
                for line in order["lines"]
            ):
                affected.append(order)
        return affected

    def _safe_stock(self, product_id: str) -> int:
        return sum(
            lot["quantity_on_hand"]
            for lot in self.store.collection("inventory_lots")
            if lot["product_id"] == product_id and lot["status"] == "available"
        )

    def restore_supply(
        self,
        *,
        event_id: str,
        scenario_id: str,
        recall_id: str,
        actor: str,
        reason: str,
    ) -> dict[str, Any]:
        return self._execute_tool(
            tool_name="restore_supply",
            event_id=event_id,
            scenario_id=scenario_id,
            actor=actor,
            reason=reason,
            operation=lambda: self._restore_supply_current(recall_id),
        )

    def _restore_supply_current(self, recall_id: str) -> dict[str, Any]:
        """Resolve records after the tool boundary refreshes shared cloud state."""

        recall = self.store.find_one("active_recalls", "recall_id", recall_id)
        if recall is None:
            raise ValueError(f"Unknown active recall {recall_id}")
        product = self.store.find_one("products", "product_id", recall["product_id"])
        if product is None:
            raise ValueError(f"Unknown product {recall['product_id']}")
        return self._run_supply_continuity(product, recall)

    def _run_supply_continuity(
        self, product: dict[str, Any], recall: dict[str, Any]
    ) -> dict[str, Any]:
        safe_stock = self._safe_stock(product["product_id"])
        target_stock = int(product["daily_demand"] * 7)
        shortage = max(0, target_stock - safe_stock)
        if shortage == 0:
            return {"actions": ["Supply Continuity found sufficient safe stock"]}

        offers = []
        suppliers = {item["supplier_id"]: item for item in self.store.collection("suppliers")}
        for offer in self.store.collection("supplier_offers"):
            supplier = suppliers[offer["supplier_id"]]
            if (
                offer["replacement_for"] == product["product_id"]
                and offer["available_quantity"] >= shortage
                and offer["certificate_status"] == "valid"
                and supplier["approved_vendor"]
            ):
                offers.append((offer, supplier))

        if not offers:
            request = {
                "approval_id": f"APPROVAL-{recall['recall_id']}",
                "type": "no_compliant_replacement",
                "status": "pending",
            }
            self.store.collection("approval_requests").append(request)
            return {"actions": ["Supply Continuity escalated: no compliant replacement"]}

        offer, supplier = min(
            offers,
            key=lambda pair: (pair[0]["lead_time_days"], pair[0]["unit_price"]),
        )
        quantity = max(shortage, offer["minimum_order"])
        total = round(quantity * offer["unit_price"], 2)
        if total > product["po_auto_approval_limit"]:
            self.store.collection("approval_requests").append(
                {
                    "approval_id": f"APPROVAL-PO-{recall['recall_id']}",
                    "type": "purchase_order",
                    "amount": total,
                    "status": "pending",
                }
            )
            return {"actions": [f"Supply Continuity requested approval for ${total:,.2f} PO"]}

        po_id = f"PO-{recall['recall_id']}"
        self.store.collection("purchase_orders").append(
            {
                "purchase_order_id": po_id,
                "recall_id": recall["recall_id"],
                "supplier_id": supplier["supplier_id"],
                "product_id": offer["product_id"],
                "quantity": quantity,
                "unit_price": offer["unit_price"],
                "total": total,
                "lead_time_days": offer["lead_time_days"],
                "status": "created",
                "freight_cost": offer["freight_cost"],
            }
        )
        return {
            "purchase_order_id": po_id,
            "actions": [
                f"Supply Continuity selected {supplier['name']} and created "
                f"{po_id} for ${total:,.2f}"
            ],
        }

    def _run_financial_recovery(
        self,
        product: dict[str, Any],
        recall: dict[str, Any],
        quarantined: list[dict[str, Any]],
        impacted_orders: list[dict[str, Any]],
        supply: dict[str, Any],
    ) -> dict[str, Any]:
        quarantined_units = sum(lot["quantity_on_hand"] for lot in quarantined)
        inventory_loss = quarantined_units * product["unit_cost"]
        refund_loss = sum(
            line["quantity"] * line["unit_price"]
            for order in impacted_orders
            for line in order["lines"]
            if line["product_id"] == product["product_id"]
            and line["lot_code"] in recall["lot_codes"]
        )
        disposal_cost = quarantined_units * 0.15
        po = self.store.find_one(
            "purchase_orders", "purchase_order_id", supply.get("purchase_order_id")
        )
        emergency_freight = float(po["freight_cost"]) if po else 0.0
        gross_loss = round(inventory_loss + refund_loss + disposal_cost + emergency_freight, 2)

        contract = self.store.find_one(
            "supplier_contracts", "supplier_id", product["supplier_id"]
        )
        liability = contract["recall_liability_percent"] if contract else 0.0
        claim_amount = round(gross_loss * liability, 2)
        approval_limit = contract["claim_auto_approval_limit"] if contract else 0.0

        held = 0
        for invoice in self.store.collection("supplier_invoices"):
            if invoice["supplier_id"] == product["supplier_id"] and invoice["status"] == "open":
                invoice["status"] = "held"
                invoice["hold_reason"] = recall["recall_id"]
                held += 1

        claim_id = f"CLAIM-{recall['recall_id']}"
        claim_status = "created" if claim_amount <= approval_limit else "approval_required"
        claim = {
            "supplier_claim_id": claim_id,
            "recall_id": recall["recall_id"],
            "supplier_id": product["supplier_id"],
            "inventory_loss": round(inventory_loss, 2),
            "customer_refunds": round(refund_loss, 2),
            "disposal_cost": round(disposal_cost, 2),
            "emergency_freight": round(emergency_freight, 2),
            "gross_loss": gross_loss,
            "claim_amount": claim_amount,
            "status": claim_status,
        }
        self.store.collection("supplier_claims").append(claim)
        if claim_status == "approval_required":
            self.store.collection("approval_requests").append(
                {
                    "approval_id": f"APPROVAL-{claim_id}",
                    "type": "supplier_claim",
                    "amount": claim_amount,
                    "status": "pending",
                }
            )

        return {
            "supplier_claim_id": claim_id,
            "actions": [
                f"Financial Recovery held {held} supplier invoice(s)",
                f"Financial Recovery calculated ${gross_loss:,.2f} loss and "
                f"{claim_status.replace('_', ' ')} {claim_id}",
            ],
        }

    def recover_finances(
        self,
        *,
        event_id: str,
        scenario_id: str,
        recall_id: str,
        purchase_order_id: str | None,
        actor: str,
        reason: str,
    ) -> dict[str, Any]:
        return self._execute_tool(
            tool_name="recover_finances",
            event_id=event_id,
            scenario_id=scenario_id,
            actor=actor,
            reason=reason,
            operation=lambda: self._recover_finances_current(
                recall_id, purchase_order_id
            ),
        )

    def _recover_finances_current(
        self,
        recall_id: str,
        purchase_order_id: str | None,
    ) -> dict[str, Any]:
        """Calculate recovery only from the state refreshed by the tool boundary."""

        recall = self.store.find_one("active_recalls", "recall_id", recall_id)
        if recall is None:
            raise ValueError(f"Unknown active recall {recall_id}")
        product = self.store.find_one("products", "product_id", recall["product_id"])
        if product is None:
            raise ValueError(f"Unknown product {recall['product_id']}")
        quarantined = [
            lot
            for lot in self.store.collection("inventory_lots")
            if lot["product_id"] == recall["product_id"]
            and lot["lot_code"] in recall["lot_codes"]
            and lot["status"] == "quarantined"
        ]
        impacted_orders = self._affected_orders(recall)
        supply = {"purchase_order_id": purchase_order_id} if purchase_order_id else {}
        return self._run_financial_recovery(
            product, recall, quarantined, impacted_orders, supply
        )

    def summary(self) -> dict[str, Any]:
        products = self.store.collection("products")
        lots = self.store.collection("inventory_lots")
        claims = self.store.collection("supplier_claims")
        return {
            "products": len(products),
            "frozen_listings": sum(item["listing_status"] == "frozen" for item in products),
            "inventory_units": sum(item["quantity_on_hand"] for item in lots),
            "quarantined_units": sum(
                item["quantity_on_hand"] for item in lots if item["status"] == "quarantined"
            ),
            "affected_customers": len(self.store.collection("notifications")),
            "purchase_orders": len(self.store.collection("purchase_orders")),
            "supplier_claims": len(claims),
            "claim_value": round(sum(item["claim_amount"] for item in claims), 2),
            "pending_approvals": sum(
                item["status"] == "pending" for item in self.store.collection("approval_requests")
            ),
            "processed_events": len(self.store.collection("processed_events")),
        }
