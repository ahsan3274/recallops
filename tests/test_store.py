from __future__ import annotations

import copy
import unittest
from pathlib import Path
from typing import Any

from app.store import FirestoreStore, LocalStore

ROOT = Path(__file__).resolve().parents[1]


class FakeSnapshot:
    def __init__(self, document_id: str, value: dict[str, Any]):
        self.id = document_id
        self._value = value

    def to_dict(self) -> dict[str, Any]:
        return copy.deepcopy(self._value)


class FakeDocument:
    def __init__(self, values: dict[str, dict[str, Any]], document_id: str):
        self.values = values
        self.document_id = document_id

    def set(self, value: dict[str, Any]) -> None:
        self.values[self.document_id] = copy.deepcopy(value)

    def delete(self) -> None:
        self.values.pop(self.document_id, None)


class FakeCollection:
    def __init__(self, values: dict[str, dict[str, Any]]):
        self.values = values

    def stream(self) -> list[FakeSnapshot]:
        return [FakeSnapshot(key, value) for key, value in sorted(self.values.items())]

    def document(self, document_id: str) -> FakeDocument:
        return FakeDocument(self.values, document_id)


class FakeFirestoreClient:
    def __init__(self):
        self.values: dict[str, dict[str, dict[str, Any]]] = {}

    def collection(self, name: str) -> FakeCollection:
        return FakeCollection(self.values.setdefault(name, {}))


class StoreContractTests(unittest.TestCase):
    def assert_contract(self, store: LocalStore) -> None:
        self.assertIsNotNone(store.find_one("products", "product_id", "PROD-001"))
        snapshot = store.snapshot()
        snapshot["products"][0]["listing_status"] = "changed-outside-store"
        self.assertNotEqual(
            store.collection("products")[0]["listing_status"], "changed-outside-store"
        )
        store.mark_processed_event("evt-contract", "scenario-contract")
        store.collection("demo_runs").append(
            {"run_id": "demo-contract", "status": "active"}
        )
        self.assertTrue(store.has_processed_event("evt-contract"))
        store.reset()
        self.assertFalse(store.has_processed_event("evt-contract"))
        self.assertIsNotNone(store.find_one("demo_runs", "run_id", "demo-contract"))

    def test_local_store_contract(self) -> None:
        self.assert_contract(LocalStore(ROOT / "seed"))

    def test_firestore_store_contract_and_persistence(self) -> None:
        client = FakeFirestoreClient()
        store = FirestoreStore(ROOT / "seed", client=client)
        self.assertEqual(
            len(store.collection("products")),
            len(LocalStore(ROOT / "seed").collection("products")),
        )

        store.find_one("products", "product_id", "PROD-001")["listing_status"] = "frozen"
        store.collection("approval_requests").append(
            {"approval_id": "APP-1", "type": "test", "status": "pending"}
        )
        store.mark_processed_event("evt-persisted", "scenario-persisted")
        store.flush()

        second = FirestoreStore(ROOT / "seed", client=client)
        self.assertEqual(
            second.find_one("products", "product_id", "PROD-001")["listing_status"],
            "frozen",
        )
        self.assertTrue(second.has_processed_event("evt-persisted"))
        self.assertEqual(second.collection("approval_requests")[0]["approval_id"], "APP-1")

        self.assert_contract(second)
        third = FirestoreStore(ROOT / "seed", client=client)
        self.assertEqual(
            third.find_one("products", "product_id", "PROD-001")["listing_status"],
            "active",
        )
        self.assertEqual(third.collection("approval_requests"), [])


if __name__ == "__main__":
    unittest.main()
