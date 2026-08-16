"""Process-wide state shared by the API and ADK agent definitions."""

from __future__ import annotations

from app.config import settings
from app.store import FirestoreStore, LocalStore, StateStore
from app.telemetry import configure_cloud_trace
from app.workflow import WorkflowEngine


def create_store() -> StateStore:
    if settings.state_backend == "local":
        return LocalStore(settings.seed_dir)
    if settings.state_backend == "firestore":
        return FirestoreStore(
            settings.seed_dir,
            project=settings.google_cloud_project,
            database=settings.firestore_database,
        )
    raise ValueError(f"Unsupported STATE_BACKEND: {settings.state_backend}")


configure_cloud_trace(
    settings.enable_cloud_trace,
    settings.google_cloud_project,
    f"recallops-{settings.agent_role}",
)
store = create_store()
engine = WorkflowEngine(store)
