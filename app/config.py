from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class Settings:
    app_env: str = os.getenv("APP_ENV", "local")
    state_backend: str = os.getenv("STATE_BACKEND", "local")
    agent_runtime_mode: str = os.getenv("AGENT_RUNTIME_MODE", "deterministic")
    demo_api_key: str = os.getenv("DEMO_API_KEY", "")
    public_dashboard: bool = os.getenv("PUBLIC_DASHBOARD", "false").lower() == "true"
    enable_public_demo: bool = os.getenv("ENABLE_PUBLIC_DEMO", "false").lower() == "true"
    public_demo_daily_limit: int = int(os.getenv("PUBLIC_DEMO_DAILY_LIMIT", "25"))
    public_demo_ttl_minutes: int = int(os.getenv("PUBLIC_DEMO_TTL_MINUTES", "30"))
    routine_model: str = os.getenv("GEMINI_ROUTINE_MODEL", "gemini-3.5-flash-lite")
    complex_model: str = os.getenv("GEMINI_COMPLEX_MODEL", "gemini-3.5-flash")
    max_model_calls: int = int(os.getenv("MAX_MODEL_CALLS_PER_WORKFLOW", "4"))
    max_daily_workflows: int = int(os.getenv("MAX_DAILY_WORKFLOWS", "100"))
    google_cloud_project: str = os.getenv("GOOGLE_CLOUD_PROJECT", "")
    google_cloud_location: str = os.getenv("GOOGLE_CLOUD_LOCATION", "global")
    agent_registry_location: str = os.getenv(
        "AGENT_REGISTRY_LOCATION", os.getenv("GOOGLE_CLOUD_LOCATION", "global")
    )
    firestore_database: str = os.getenv("FIRESTORE_DATABASE", "(default)")
    pubsub_topic: str = os.getenv("PUBSUB_TOPIC", "enterprise-events")
    pubsub_push_audience: str = os.getenv("PUBSUB_PUSH_AUDIENCE", "")
    pubsub_push_service_account: str = os.getenv("PUBSUB_PUSH_SERVICE_ACCOUNT", "")
    agent_role: str = os.getenv("AGENT_ROLE", "recall")
    public_base_url: str = os.getenv("PUBLIC_BASE_URL", "http://localhost:8000")
    supply_agent_resource: str = os.getenv("SUPPLY_AGENT_RESOURCE", "agents/supply-agent")
    finance_agent_resource: str = os.getenv("FINANCE_AGENT_RESOURCE", "agents/finance-agent")
    enable_cloud_trace: bool = os.getenv("ENABLE_CLOUD_TRACE", "false").lower() == "true"
    root_dir: Path = Path(__file__).resolve().parents[1]

    @property
    def seed_dir(self) -> Path:
        return self.root_dir / "seed"

    @property
    def scenario_dir(self) -> Path:
        return self.root_dir / "scenarios"


settings = Settings()
