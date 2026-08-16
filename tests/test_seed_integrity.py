from __future__ import annotations

import unittest
from pathlib import Path

from app.store import LocalStore


ROOT = Path(__file__).resolve().parents[1]


class SeedIntegrityTests(unittest.TestCase):
    def setUp(self) -> None:
        self.store = LocalStore(ROOT / "seed")

    def test_references_are_valid(self) -> None:
        product_ids = {item["product_id"] for item in self.store.collection("products")}
        supplier_ids = {item["supplier_id"] for item in self.store.collection("suppliers")}
        warehouse_ids = {item["warehouse_id"] for item in self.store.collection("warehouses")}

        for product in self.store.collection("products"):
            self.assertIn(product["supplier_id"], supplier_ids)
        for lot in self.store.collection("inventory_lots"):
            self.assertIn(lot["product_id"], product_ids)
            self.assertIn(lot["warehouse_id"], warehouse_ids)
        for order in self.store.collection("orders"):
            for line in order["lines"]:
                self.assertIn(line["product_id"], product_ids)
        for offer in self.store.collection("supplier_offers"):
            self.assertIn(offer["supplier_id"], supplier_ids)
            self.assertIn(offer["product_id"], product_ids)
            self.assertIn(offer["replacement_for"], product_ids)

    def test_synthetic_customer_addresses_use_reserved_domain(self) -> None:
        for order in self.store.collection("orders"):
            self.assertTrue(order["customer_email"].endswith("@example.invalid"))


if __name__ == "__main__":
    unittest.main()
