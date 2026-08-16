#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import random
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
SEED_DIR = ROOT / "seed"


def write_json(name: str, value: Any) -> None:
    SEED_DIR.mkdir(parents=True, exist_ok=True)
    (SEED_DIR / name).write_text(
        json.dumps(value, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )


def build_products(count: int) -> list[dict[str, Any]]:
    core = [
        {
            "product_id": "PROD-001",
            "sku": "PB-441",
            "gtin": "00812345678901",
            "name": "GreenFields Crunchy Peanut Butter 16 oz",
            "category": "Nut butters",
            "supplier_id": "SUP-001",
            "unit_cost": 3.10,
            "sale_price": 5.49,
            "daily_demand": 45,
            "po_auto_approval_limit": 5000.0,
            "listing_status": "active",
        },
        {
            "product_id": "PROD-002",
            "sku": "PB-442",
            "gtin": "00812345678918",
            "name": "SunTrail Creamy Peanut Butter 16 oz",
            "category": "Nut butters",
            "supplier_id": "SUP-002",
            "unit_cost": 3.25,
            "sale_price": 5.69,
            "daily_demand": 35,
            "po_auto_approval_limit": 5000.0,
            "listing_status": "active",
        },
        {
            "product_id": "PROD-003",
            "sku": "PB-443",
            "gtin": "00812345678925",
            "name": "ValueHarvest Peanut Spread 16 oz",
            "category": "Nut butters",
            "supplier_id": "SUP-003",
            "unit_cost": 2.55,
            "sale_price": 4.79,
            "daily_demand": 30,
            "po_auto_approval_limit": 5000.0,
            "listing_status": "active",
        },
        {
            "product_id": "PROD-004",
            "sku": "PB-444",
            "gtin": "00812345678932",
            "name": "LongRoad Organic Peanut Butter 16 oz",
            "category": "Nut butters",
            "supplier_id": "SUP-004",
            "unit_cost": 3.35,
            "sale_price": 6.10,
            "daily_demand": 22,
            "po_auto_approval_limit": 5000.0,
            "listing_status": "active",
        },
    ]
    categories = ["Breakfast", "Snacks", "Sauces", "Canned foods", "Beverages"]
    for number in range(len(core) + 1, count + 1):
        supplier_number = ((number - 1) % 4) + 1
        core.append(
            {
                "product_id": f"PROD-{number:03d}",
                "sku": f"FC-{number:04d}",
                "gtin": f"00990000{number:06d}",
                "name": f"FreshCart Demo Product {number:03d}",
                "category": categories[number % len(categories)],
                "supplier_id": f"SUP-{supplier_number:03d}",
                "unit_cost": round(1.2 + (number % 17) * 0.21, 2),
                "sale_price": round(2.4 + (number % 17) * 0.37, 2),
                "daily_demand": 5 + number % 25,
                "po_auto_approval_limit": 5000.0,
                "listing_status": "active",
            }
        )
    return core


def build_orders(rng: random.Random, count: int, products: list[dict[str, Any]]) -> list[dict[str, Any]]:
    orders = []
    affected_lots = ["L2408", "L2409", "L2410"]
    start = datetime(2026, 7, 1, tzinfo=UTC)
    for number in range(1, count + 1):
        is_affected = number <= max(12, count // 4)
        product = products[0] if is_affected else rng.choice(products[1:])
        lot_code = rng.choice(affected_lots) if is_affected else f"L25{rng.randint(1, 12):02d}"
        quantity = rng.randint(1, 3)
        orders.append(
            {
                "order_id": f"ORDER-{number:05d}",
                "customer_id": f"CUST-{number:05d}",
                "customer_email": f"customer{number:05d}@example.invalid",
                "ordered_at": (start + timedelta(hours=number * 7)).isoformat(),
                "status": "fulfilled",
                "lines": [
                    {
                        "product_id": product["product_id"],
                        "lot_code": lot_code,
                        "quantity": quantity,
                        "unit_price": product["sale_price"],
                    }
                ],
            }
        )
    return orders


def main() -> None:
    parser = argparse.ArgumentParser(description="Generate deterministic RecallOps seed data")
    parser.add_argument("--random-seed", type=int, default=42)
    parser.add_argument("--products", type=int, default=40)
    parser.add_argument("--orders", type=int, default=80)
    parser.add_argument("--as-of", default="2026-08-16T00:00:00Z")
    args = parser.parse_args()
    if args.products < 4:
        parser.error("--products must be at least 4")
    rng = random.Random(args.random_seed)

    suppliers = [
        {
            "supplier_id": "SUP-001",
            "name": "Orchard Peak Foods",
            "approved_vendor": True,
            "certificate_status": "valid",
            "reliability": 0.91,
        },
        {
            "supplier_id": "SUP-002",
            "name": "SafeHarbor Foods",
            "approved_vendor": True,
            "certificate_status": "valid",
            "reliability": 0.94,
        },
        {
            "supplier_id": "SUP-003",
            "name": "Budget Pantry Co",
            "approved_vendor": True,
            "certificate_status": "expired",
            "reliability": 0.88,
        },
        {
            "supplier_id": "SUP-004",
            "name": "LongRoad Organics",
            "approved_vendor": True,
            "certificate_status": "valid",
            "reliability": 0.86,
        },
    ]
    warehouses = [
        {"warehouse_id": "WH-ATL", "name": "Atlanta Distribution Center", "region": "US-SE"},
        {"warehouse_id": "WH-CHI", "name": "Chicago Distribution Center", "region": "US-MW"},
        {"warehouse_id": "WH-DEN", "name": "Denver Distribution Center", "region": "US-W"},
    ]
    products = build_products(args.products)
    inventory_lots = [
        {"lot_id": "LOT-001", "lot_code": "L2408", "product_id": "PROD-001", "warehouse_id": "WH-ATL", "quantity_on_hand": 120, "status": "available"},
        {"lot_id": "LOT-002", "lot_code": "L2409", "product_id": "PROD-001", "warehouse_id": "WH-CHI", "quantity_on_hand": 160, "status": "available"},
        {"lot_id": "LOT-003", "lot_code": "L2410", "product_id": "PROD-001", "warehouse_id": "WH-DEN", "quantity_on_hand": 90, "status": "available"},
        {"lot_id": "LOT-004", "lot_code": "L2501", "product_id": "PROD-001", "warehouse_id": "WH-ATL", "quantity_on_hand": 80, "status": "available"},
        {"lot_id": "LOT-005", "lot_code": "L2503", "product_id": "PROD-002", "warehouse_id": "WH-CHI", "quantity_on_hand": 60, "status": "available"},
    ]
    for number, product in enumerate(products[4:], start=6):
        inventory_lots.append(
            {
                "lot_id": f"LOT-{number:03d}",
                "lot_code": f"L25{(number % 12) + 1:02d}",
                "product_id": product["product_id"],
                "warehouse_id": warehouses[number % len(warehouses)]["warehouse_id"],
                "quantity_on_hand": rng.randint(30, 240),
                "status": "available",
            }
        )

    offers = [
        {"offer_id": "OFFER-001", "supplier_id": "SUP-002", "product_id": "PROD-002", "replacement_for": "PROD-001", "unit_price": 3.40, "minimum_order": 200, "available_quantity": 5000, "lead_time_days": 1, "certificate_status": "valid", "freight_cost": 250.0},
        {"offer_id": "OFFER-002", "supplier_id": "SUP-003", "product_id": "PROD-003", "replacement_for": "PROD-001", "unit_price": 2.75, "minimum_order": 150, "available_quantity": 8000, "lead_time_days": 1, "certificate_status": "expired", "freight_cost": 210.0},
        {"offer_id": "OFFER-003", "supplier_id": "SUP-004", "product_id": "PROD-004", "replacement_for": "PROD-001", "unit_price": 3.10, "minimum_order": 200, "available_quantity": 7000, "lead_time_days": 5, "certificate_status": "valid", "freight_cost": 175.0},
    ]
    contracts = [
        {"contract_id": "CONTRACT-001", "supplier_id": "SUP-001", "recall_liability_percent": 0.90, "claim_auto_approval_limit": 5000.0, "payment_terms_days": 30},
        {"contract_id": "CONTRACT-002", "supplier_id": "SUP-002", "recall_liability_percent": 0.80, "claim_auto_approval_limit": 5000.0, "payment_terms_days": 30},
        {"contract_id": "CONTRACT-003", "supplier_id": "SUP-003", "recall_liability_percent": 0.70, "claim_auto_approval_limit": 3500.0, "payment_terms_days": 45},
        {"contract_id": "CONTRACT-004", "supplier_id": "SUP-004", "recall_liability_percent": 0.85, "claim_auto_approval_limit": 5000.0, "payment_terms_days": 30},
    ]
    invoices = [
        {"invoice_id": "SINV-001", "supplier_id": "SUP-001", "amount": 4200.0, "status": "open", "product_ids": ["PROD-001"]},
        {"invoice_id": "SINV-002", "supplier_id": "SUP-001", "amount": 2800.0, "status": "paid", "product_ids": ["PROD-001"]},
        {"invoice_id": "SINV-003", "supplier_id": "SUP-002", "amount": 3100.0, "status": "open", "product_ids": ["PROD-002"]},
    ]

    write_json("products.json", products)
    write_json("suppliers.json", suppliers)
    write_json("warehouses.json", warehouses)
    write_json("inventory_lots.json", inventory_lots)
    write_json("orders.json", build_orders(rng, args.orders, products))
    write_json("supplier_offers.json", offers)
    write_json("supplier_contracts.json", contracts)
    write_json("supplier_invoices.json", invoices)
    write_json(
        "source_manifest.json",
        [
            {
                "source": "RecallOps deterministic generator",
                "retrieved_at": args.as_of,
                "licence": "MIT",
                "random_seed": args.random_seed,
                "products": args.products,
                "orders": args.orders,
                "transform_version": "0.1.0",
            }
        ],
    )
    print(f"Generated seed data in {SEED_DIR}")


if __name__ == "__main__":
    main()
