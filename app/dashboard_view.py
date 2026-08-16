"""Curated, synthetic-only views for the public RecallOps control room."""

from __future__ import annotations

from typing import Any

from app.demo import GuidedDemoController
from app.store import StateStore

AGENTS = (
    {
        "id": "recall_coordinator",
        "department": "Product Safety",
        "name": "Recall Coordinator",
        "color": "blue",
        "mission": "Contain product risk and protect customers",
        "capabilities": ["Match recalls", "Freeze listings", "Quarantine lots", "Prepare notices"],
        "data": ["Products", "Inventory lots", "Orders", "Active recalls"],
    },
    {
        "id": "supply_continuity",
        "department": "Procurement",
        "name": "Supply Continuity",
        "color": "green",
        "mission": "Restore safe stock without bypassing supplier policy",
        "capabilities": ["Forecast shortage", "Validate certificates", "Rank offers", "Create POs"],
        "data": ["Demand", "Suppliers", "Offers", "Purchase orders"],
    },
    {
        "id": "financial_recovery",
        "department": "Finance / Admin",
        "name": "Financial Recovery",
        "color": "yellow",
        "mission": "Quantify loss and recover contract-backed value",
        "capabilities": ["Calculate loss", "Hold invoices", "Read contracts", "Create claims"],
        "data": ["Invoices", "Contracts", "Refunds", "Supplier claims"],
    },
)

EVENT_META = (
    {
        "step": "transfer",
        "title": "Transfer inventory",
        "short_title": "Transfer stock",
        "source": "Warehouse simulator",
        "description": "Move 20 units of lot L2409 from Chicago to Denver.",
        "expected": "Chicago −20 · Denver +20",
    },
    {
        "step": "recall",
        "title": "Issue Class I recall",
        "short_title": "Issue recall",
        "source": "FDA feed simulator",
        "description": "Recall PROD-001 and affected lots L2408 through L2411.",
        "expected": "Recall → Supply → Finance",
    },
    {
        "step": "late-arrival",
        "title": "Receive late recalled stock",
        "short_title": "Receive late lot",
        "source": "Warehouse simulator",
        "description": "Receive 30 units of recalled lot L2411 in Chicago.",
        "expected": "Receive +30 · Quarantine +30",
    },
    {
        "step": "duplicate",
        "title": "Deliver duplicate event",
        "short_title": "Test duplicate",
        "source": "Pub/Sub retry",
        "description": "Deliver evt-receipt-001 again with the same idempotency key.",
        "expected": "HTTP 200 · No second mutation",
    },
)

ACTION_META = {
    "transfer_inventory": ("Inventory moved", "tool"),
    "contain_recall": ("Recall contained", "tool"),
    "restore_supply": ("Replacement supply secured", "specialist"),
    "recover_finances": ("Financial recovery prepared", "specialist"),
    "receive_inventory": ("Late stock evaluated", "tool"),
    "handoff_supply_continuity": ("Recall ↔ Supply A2A exchange", "handoff"),
    "handoff_financial_recovery": ("Recall ↔ Finance A2A exchange", "handoff"),
}

AGENT_LABELS = {
    "recall_coordinator": "Recall Coordinator",
    "supply_continuity": "Supply Continuity",
    "financial_recovery": "Financial Recovery",
}


def company_snapshot(store: StateStore) -> dict[str, Any]:
    store.refresh()
    products = store.collection("products")
    lots = store.collection("inventory_lots")
    orders = store.collection("orders")
    warehouses = {item["warehouse_id"]: item for item in store.collection("warehouses")}
    suppliers = {item["supplier_id"]: item for item in store.collection("suppliers")}
    product = store.find_one("products", "product_id", "PROD-001") or {}
    active_recall = store.find_one("active_recalls", "product_id", "PROD-001")
    affected_lots = set(
        (active_recall or {}).get("lot_codes", ["L2408", "L2409", "L2410", "L2411"])
    )
    product_lots = []
    for lot in lots:
        if lot.get("product_id") != "PROD-001":
            continue
        warehouse = warehouses.get(lot.get("warehouse_id"), {})
        product_lots.append(
            {
                "lot_id": lot.get("lot_id"),
                "lot_code": lot.get("lot_code"),
                "warehouse_id": lot.get("warehouse_id"),
                "warehouse": warehouse.get("name", lot.get("warehouse_id")),
                "quantity": lot.get("quantity_on_hand", 0),
                "status": lot.get("status", "unknown"),
                "affected": lot.get("lot_code") in affected_lots,
            }
        )
    product_lots.sort(key=lambda item: (str(item["lot_code"]), str(item["warehouse_id"])))

    affected_orders = sum(
        any(
            line.get("product_id") == "PROD-001" and line.get("lot_code") in affected_lots
            for line in order.get("lines", [])
        )
        for order in orders
    )
    purchase_order = next(iter(store.collection("purchase_orders")), None)
    claim = next(iter(store.collection("supplier_claims")), None)

    offers = []
    for offer in store.collection("supplier_offers"):
        if offer.get("replacement_for") != "PROD-001":
            continue
        supplier = suppliers.get(offer["supplier_id"], {})
        offers.append(
            {
                "offer_id": offer["offer_id"],
                "supplier_id": offer["supplier_id"],
                "supplier": supplier.get("name", offer["supplier_id"]),
                "certificate_status": offer.get(
                    "certificate_status", supplier.get("certificate_status", "unknown")
                ),
                "reliability": supplier.get("reliability"),
                "unit_price": offer.get("unit_price"),
                "lead_time_days": offer.get("lead_time_days"),
                "available_quantity": offer.get("available_quantity"),
                "selected": bool(
                    purchase_order
                    and purchase_order.get("supplier_id") == offer.get("supplier_id")
                ),
            }
        )
    offers.sort(key=lambda item: (not item["selected"], item["lead_time_days"]))

    invoice = store.find_one("supplier_invoices", "invoice_id", "SINV-001")
    contract = store.find_one("supplier_contracts", "supplier_id", "SUP-001")
    return {
        "agents": list(AGENTS),
        "counts": {
            "products": len(products),
            "inventory_lots": len(lots),
            "orders": len(orders),
            "suppliers": len(suppliers),
            "warehouses": len(warehouses),
            "contracts": len(store.collection("supplier_contracts")),
            "invoices": len(store.collection("supplier_invoices")),
        },
        "case": {
            "product_id": product.get("product_id"),
            "name": product.get("name"),
            "sku": product.get("sku"),
            "gtin": product.get("gtin"),
            "listing_status": product.get("listing_status"),
            "daily_demand": product.get("daily_demand"),
            "affected_orders": affected_orders,
            "recall": active_recall,
            "lots": product_lots,
        },
        "procurement": {"offers": offers, "purchase_order": purchase_order},
        "finance": {"invoice": invoice, "contract": contract, "claim": claim},
    }


def story_snapshot(
    store: StateStore,
    demo: GuidedDemoController,
) -> dict[str, Any]:
    store.refresh()
    status = demo.latest_status()
    step_status = {
        item["name"]: item for item in (status or {}).get("steps", [])
    }
    processed = {item.get("event_id") for item in store.collection("processed_events")}
    audits = list(store.collection("audit_events"))

    handoff_targets = {
        item.get("to_agent")
        for item in audits
        if item.get("resource_type") == "a2a_agent"
    }
    tool_audits = []
    for item in audits:
        action = item.get("action")
        if action not in ACTION_META:
            continue
        if action == "restore_supply" and "supply_continuity" in handoff_targets:
            continue
        if action == "recover_finances" and "financial_recovery" in handoff_targets:
            continue
        tool_audits.append(item)

    event_groups = []
    for index, (meta, event) in enumerate(
        zip(EVENT_META, demo.events, strict=True)
    ):
        is_duplicate = meta["step"] == "duplicate"
        if status:
            completed = bool(step_status.get(meta["step"], {}).get("completed"))
            available = bool(step_status.get(meta["step"], {}).get("available"))
        else:
            completed = event.event_id in processed and not is_duplicate
            available = False

        actions = []
        if not is_duplicate:
            for audit in tool_audits:
                if audit.get("event_id") != event.event_id:
                    continue
                title, kind = ACTION_META[audit["action"]]
                actions.append(
                    {
                        "actor": audit.get("actor"),
                        "agent": AGENT_LABELS.get(audit.get("actor"), audit.get("actor")),
                        "title": title,
                        "kind": kind,
                        "reason": audit.get("reason"),
                        "messages": list(audit.get("actions", [])),
                        "trace_id": audit.get("trace_id"),
                        "occurred_at": audit.get("occurred_at"),
                        "from_agent": audit.get("from_agent"),
                        "to_agent": audit.get("to_agent"),
                    }
                )
            order = {
                "transfer_inventory": 10,
                "contain_recall": 10,
                "handoff_supply_continuity": 20,
                "restore_supply": 20,
                "handoff_financial_recovery": 30,
                "recover_finances": 30,
                "receive_inventory": 10,
            }
            actions.sort(
                key=lambda action: order.get(
                    next(
                        (
                            audit.get("action")
                            for audit in tool_audits
                            if audit.get("event_id") == event.event_id
                            and ACTION_META[audit["action"]][0] == action["title"]
                        ),
                        "",
                    ),
                    99,
                )
            )
        elif completed:
            actions.append(
                {
                    "actor": "event_gateway",
                    "agent": "Idempotency Gate",
                    "title": "Duplicate safely ignored",
                    "kind": "guardrail",
                    "reason": "The event ID was already committed",
                    "messages": [
                        "Pub/Sub delivery acknowledged with HTTP 200",
                        "No second inventory mutation or business audit was created",
                    ],
                    "trace_id": None,
                    "occurred_at": (status or {}).get("duplicate_confirmed_at"),
                    "from_agent": None,
                    "to_agent": None,
                }
            )

        event_groups.append(
            {
                **meta,
                "index": index + 1,
                "event_id": event.event_id,
                "event_type": event.event_type,
                "occurred_at": event.occurred_at,
                "completed": completed,
                "available": available,
                "actions": actions,
            }
        )
    return {"demo": status, "events": event_groups}
