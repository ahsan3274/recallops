from __future__ import annotations

import copy
import hashlib
import json
from pathlib import Path
from typing import Any, Protocol

SEED_FILES = {
    "products": "products.json",
    "suppliers": "suppliers.json",
    "warehouses": "warehouses.json",
    "inventory_lots": "inventory_lots.json",
    "orders": "orders.json",
    "supplier_offers": "supplier_offers.json",
    "supplier_contracts": "supplier_contracts.json",
    "supplier_invoices": "supplier_invoices.json",
}

RUNTIME_COLLECTIONS = (
    "active_recalls",
    "purchase_orders",
    "supplier_claims",
    "notifications",
    "approval_requests",
    "warehouse_tasks",
    "audit_events",
    "tool_executions",
    "processed_events",
)

CONTROL_COLLECTIONS = ("demo_runs",)

ALL_COLLECTIONS = (*SEED_FILES, *RUNTIME_COLLECTIONS, *CONTROL_COLLECTIONS)

DOCUMENT_ID_FIELDS = {
    "products": "product_id",
    "suppliers": "supplier_id",
    "warehouses": "warehouse_id",
    "inventory_lots": "lot_id",
    "orders": "order_id",
    "supplier_offers": "offer_id",
    "supplier_contracts": "contract_id",
    "supplier_invoices": "invoice_id",
    "active_recalls": "recall_id",
    "purchase_orders": "purchase_order_id",
    "supplier_claims": "supplier_claim_id",
    "notifications": "notification_id",
    "approval_requests": "approval_id",
    "warehouse_tasks": "task_id",
    "tool_executions": "idempotency_key",
    "processed_events": "event_id",
    "audit_events": "audit_id",
    "demo_runs": "run_id",
}


class StateStore(Protocol):
    state: dict[str, Any]

    def reset(self) -> None: ...

    def refresh(self) -> None: ...

    def flush(self) -> None: ...

    def collection(self, name: str) -> list[dict[str, Any]]: ...

    def find_one(self, collection: str, key: str, value: Any) -> dict[str, Any] | None: ...

    def snapshot(self) -> dict[str, Any]: ...

    def has_processed_event(self, event_id: str) -> bool: ...

    def mark_processed_event(
        self,
        event_id: str,
        scenario_id: str,
        event_type: str = "",
        processed_at: str = "",
    ) -> None: ...


class LocalStore:
    """In-memory store used by local demos and tests.

    FirestoreStore should implement the same small interface in the Google Cloud
    milestone. Keeping this implementation deterministic makes evaluation easy.
    """

    def __init__(self, seed_dir: Path):
        self.seed_dir = seed_dir
        self._seed_state = self._load_seed()
        self.state: dict[str, Any] = {}
        self.reset()

    def _load_seed(self) -> dict[str, Any]:
        state: dict[str, Any] = {}
        for collection, filename in SEED_FILES.items():
            path = self.seed_dir / filename
            if not path.exists():
                raise FileNotFoundError(
                    f"Missing {path}. Run `python scripts/generate_seed.py` first."
                )
            state[collection] = json.loads(path.read_text(encoding="utf-8"))
        return state

    def reset(self) -> None:
        demo_runs = copy.deepcopy(getattr(self, "state", {}).get("demo_runs", []))
        self.state = copy.deepcopy(self._seed_state)
        for name in RUNTIME_COLLECTIONS:
            self.state[name] = []
        self.state["demo_runs"] = demo_runs

    def refresh(self) -> None:
        """Local state is already current."""

    def flush(self) -> None:
        """Local mutations are immediately visible in memory."""

    def collection(self, name: str) -> list[dict[str, Any]]:
        value = self.state.setdefault(name, [])
        if not isinstance(value, list):
            raise TypeError(f"Collection {name} is not a list")
        return value

    def find_one(self, collection: str, key: str, value: Any) -> dict[str, Any] | None:
        return next((item for item in self.collection(collection) if item.get(key) == value), None)

    def snapshot(self) -> dict[str, Any]:
        return copy.deepcopy(self.state)

    def has_processed_event(self, event_id: str) -> bool:
        return self.find_one("processed_events", "event_id", event_id) is not None

    def mark_processed_event(
        self,
        event_id: str,
        scenario_id: str,
        event_type: str = "",
        processed_at: str = "",
    ) -> None:
        self.collection("processed_events").append(
            {
                "event_id": event_id,
                "scenario_id": scenario_id,
                "event_type": event_type,
                "processed_at": processed_at,
            }
        )


class FirestoreStore(LocalStore):
    """Firestore-backed implementation with a small deterministic working set.

    Each tool refreshes before applying policy and flushes after mutation. Cloud Run's
    max-instance setting is one per agent service; document IDs make retries idempotent.
    """

    def __init__(
        self,
        seed_dir: Path,
        *,
        project: str | None = None,
        database: str = "(default)",
        client: Any | None = None,
    ):
        if client is None:
            try:
                from google.cloud import firestore
            except ImportError as exc:
                raise RuntimeError(
                    "Firestore backend requires `pip install -e \".[google]\"`"
                ) from exc
            client = firestore.Client(project=project or None, database=database)
        self.client = client
        self._cloud_ready = False
        super().__init__(seed_dir)
        self._cloud_ready = True
        if any(self.client.collection("products").stream()):
            self.refresh()
        else:
            self.flush()

    def reset(self) -> None:
        super().reset()
        if getattr(self, "_cloud_ready", False):
            self.flush()

    def refresh(self) -> None:
        state: dict[str, Any] = {}
        for name in ALL_COLLECTIONS:
            state[name] = [snapshot.to_dict() for snapshot in self.client.collection(name).stream()]
        self.state = state

    def flush(self) -> None:
        for name in ALL_COLLECTIONS:
            collection = self.client.collection(name)
            desired: dict[str, dict[str, Any]] = {}
            for item in self.collection(name):
                document_id = self._document_id(name, item)
                desired[document_id] = copy.deepcopy(item)
            existing = {snapshot.id for snapshot in collection.stream()}
            for document_id, item in desired.items():
                collection.document(document_id).set(item)
            for document_id in existing.difference(desired):
                collection.document(document_id).delete()

    @staticmethod
    def _document_id(collection: str, item: dict[str, Any]) -> str:
        id_field = DOCUMENT_ID_FIELDS.get(collection)
        if id_field and item.get(id_field):
            return str(item[id_field]).replace("/", "_")
        canonical = json.dumps(item, sort_keys=True, separators=(",", ":"), default=str)
        return hashlib.sha256(canonical.encode("utf-8")).hexdigest()
