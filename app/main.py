from __future__ import annotations

import base64
import binascii
import json
import secrets
from pathlib import Path
from typing import Any

from fastapi import Depends, FastAPI, Header, HTTPException, Request
from fastapi.responses import FileResponse, JSONResponse

from app.a2a import A2AServer
from app.adk_runtime import AdkEventRuntime
from app.config import settings
from app.dashboard_view import company_snapshot, story_snapshot
from app.demo import GuidedDemoController, GuidedDemoError
from app.events import PubSubPublisher, verify_pubsub_oidc
from app.models import EnterpriseEvent
from app.runtime_state import engine, store

app = FastAPI(title="RecallOps", version="0.1.0")
a2a_server = A2AServer(
    settings.agent_role,
    engine,
    settings.root_dir / "agent_cards",
    settings.public_base_url,
)
_adk_runtime: AdkEventRuntime | None = None
guided_demo = GuidedDemoController(
    store,
    settings.scenario_dir / "recall_peanut_01.jsonl",
    daily_limit=settings.public_demo_daily_limit,
    ttl_minutes=settings.public_demo_ttl_minutes,
)

PUBLIC_DASHBOARD_GET_PATHS = {
    "/",
    "/health",
    "/api/summary",
    "/api/audit",
    "/api/company",
    "/api/story",
    "/api/demo/status",
    "/.well-known/agent-card.json",
}
PUBLIC_GUIDED_DEMO_POST_PATHS = {
    "/api/demo/start",
    "/api/demo/events/transfer",
    "/api/demo/events/recall",
    "/api/demo/events/late-arrival",
    "/api/demo/events/duplicate",
}

if settings.agent_runtime_mode == "adk":
    from app.adk_a2a import install_adk_a2a_routes
    from app.agents.definitions import root_agent

    install_adk_a2a_routes(app, root_agent, a2a_server.agent_card())


def get_adk_runtime() -> AdkEventRuntime:
    global _adk_runtime
    if _adk_runtime is None:
        _adk_runtime = AdkEventRuntime.create()
    return _adk_runtime


def valid_demo_key(candidate: str | None) -> bool:
    return bool(
        settings.demo_api_key
        and candidate
        and secrets.compare_digest(candidate, settings.demo_api_key)
    )


def require_demo_key(x_demo_key: str | None = Header(default=None)) -> None:
    if settings.public_dashboard and not valid_demo_key(x_demo_key):
        raise HTTPException(status_code=403, detail="Public dashboard is read-only")
    if settings.demo_api_key and not valid_demo_key(x_demo_key):
        raise HTTPException(status_code=401, detail="Missing or invalid X-Demo-Key")


@app.middleware("http")
async def public_dashboard_guard(request: Request, call_next: Any) -> Any:
    """Expose only read-only submission routes when the Recall service is public."""

    if not settings.public_dashboard:
        return await call_next(request)
    path = request.url.path.rstrip("/") or "/"
    if request.method == "GET" and path in PUBLIC_DASHBOARD_GET_PATHS:
        return await call_next(request)
    if request.method == "POST" and path == "/api/pubsub":
        return await call_next(request)
    if (
        settings.enable_public_demo
        and request.method == "POST"
        and path in PUBLIC_GUIDED_DEMO_POST_PATHS
    ):
        return await call_next(request)
    if valid_demo_key(request.headers.get("X-Demo-Key")):
        return await call_next(request)
    return JSONResponse(status_code=403, content={"detail": "Public dashboard is read-only"})


def require_pubsub_identity(
    authorization: str | None = Header(default=None),
    x_demo_key: str | None = Header(default=None),
) -> None:
    if settings.app_env == "local":
        require_demo_key(x_demo_key)
        return
    try:
        verify_pubsub_oidc(
            authorization,
            audience=settings.pubsub_push_audience,
            expected_email=settings.pubsub_push_service_account,
        )
    except (PermissionError, RuntimeError, ValueError) as exc:
        raise HTTPException(status_code=401, detail="Invalid Pub/Sub identity") from exc


@app.get("/", include_in_schema=False)
def dashboard() -> FileResponse:
    return FileResponse(Path(__file__).parent / "static" / "index.html")


@app.get("/health")
def health() -> dict[str, str]:
    dashboard_mode = "operator"
    if settings.public_dashboard:
        dashboard_mode = (
            "public-guided-demo" if settings.enable_public_demo else "public-read-only"
        )
    return {
        "status": "ok",
        "environment": settings.app_env,
        "runtime_mode": settings.agent_runtime_mode,
        "dashboard_mode": dashboard_mode,
    }


if settings.agent_runtime_mode != "adk":

    @app.get("/.well-known/agent-card.json")
    def agent_card() -> dict[str, Any]:
        return a2a_server.agent_card()

    @app.post("/a2a")
    def a2a_message(payload: dict[str, Any]) -> dict[str, Any]:
        return a2a_server.handle(payload)


@app.get("/api/summary")
def summary() -> dict[str, Any]:
    return engine.summary()


@app.get("/api/audit")
def audit() -> list[dict[str, Any]]:
    return store.collection("audit_events")


@app.get("/api/company")
def company() -> dict[str, Any]:
    return company_snapshot(store)


@app.get("/api/story")
def story() -> dict[str, Any]:
    return story_snapshot(store, guided_demo)


def require_guided_demo() -> None:
    if settings.app_env != "local" and not settings.enable_public_demo:
        raise HTTPException(status_code=403, detail="Guided public demo is disabled")


def guided_demo_error(exc: GuidedDemoError) -> HTTPException:
    status_code = 429 if "safety limit" in str(exc) else 409
    return HTTPException(status_code=status_code, detail=str(exc))


@app.post("/api/demo/start")
def start_guided_demo() -> dict[str, Any]:
    require_guided_demo()
    try:
        return {"status": "ready", "demo": guided_demo.start(), "summary": engine.summary()}
    except GuidedDemoError as exc:
        raise guided_demo_error(exc) from exc


@app.get("/api/demo/status")
def guided_demo_status(x_demo_run: str | None = Header(default=None)) -> dict[str, Any]:
    require_guided_demo()
    try:
        return {
            "demo": guided_demo.status(x_demo_run or ""),
            "summary": engine.summary(),
        }
    except GuidedDemoError as exc:
        raise guided_demo_error(exc) from exc


@app.post("/api/demo/events/{step_name}")
def run_guided_demo_step(
    step_name: str,
    x_demo_run: str | None = Header(default=None),
) -> dict[str, Any]:
    require_guided_demo()
    run_id = x_demo_run or ""
    try:
        event = guided_demo.prepare_step(run_id, step_name)
    except GuidedDemoError as exc:
        raise guided_demo_error(exc) from exc

    try:
        if settings.app_env == "production":
            message_id = PubSubPublisher(
                settings.google_cloud_project,
                settings.pubsub_topic,
            ).publish(event)
            return {
                "status": "published",
                "message_id": message_id,
                "event_id": event.event_id,
                "event_type": event.event_type,
            }
        result = engine.process(event)
        if result.get("status") == "duplicate_ignored":
            guided_demo.confirm_duplicate(event.event_id)
        return {"status": "processed", "result": result}
    except Exception:
        guided_demo.rollback_step(run_id, step_name)
        raise


@app.get("/api/state", dependencies=[Depends(require_demo_key)])
def state() -> dict[str, Any]:
    return store.snapshot()


@app.post("/api/reset", dependencies=[Depends(require_demo_key)])
def reset() -> dict[str, Any]:
    store.reset()
    return {"status": "reset", "summary": engine.summary()}


@app.post("/api/events", dependencies=[Depends(require_demo_key)])
def process_event(payload: dict[str, Any]) -> dict[str, Any]:
    return engine.process(EnterpriseEvent.from_dict(payload))


@app.post("/api/events/publish", dependencies=[Depends(require_demo_key)])
def publish_event(payload: dict[str, Any]) -> dict[str, str]:
    event = EnterpriseEvent.from_dict(payload)
    publisher = PubSubPublisher(
        settings.google_cloud_project,
        settings.pubsub_topic,
    )
    return {"status": "published", "message_id": publisher.publish(event)}


@app.post("/api/scenarios/{scenario_name}/replay", dependencies=[Depends(require_demo_key)])
def replay(scenario_name: str) -> dict[str, Any]:
    if not scenario_name.replace("-", "").replace("_", "").isalnum():
        raise HTTPException(status_code=400, detail="Invalid scenario name")
    path = settings.scenario_dir / f"{scenario_name}.jsonl"
    if not path.exists():
        raise HTTPException(status_code=404, detail="Scenario not found")
    results = []
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if line:
            results.append(engine.process(EnterpriseEvent.from_dict(json.loads(line))))
    return {"scenario": scenario_name, "results": results, "summary": engine.summary()}


@app.post("/api/pubsub", dependencies=[Depends(require_pubsub_identity)])
async def pubsub_push(envelope: dict[str, Any]) -> dict[str, Any]:
    """Accept a standard Pub/Sub push envelope.

    Production verifies the Google-signed OIDC token, audience, and configured
    push service-account email before this handler is invoked.
    """

    try:
        encoded = envelope["message"]["data"]
        payload = json.loads(base64.b64decode(encoded).decode("utf-8"))
    except (KeyError, ValueError, binascii.Error, json.JSONDecodeError) as exc:
        raise HTTPException(status_code=400, detail="Invalid Pub/Sub envelope") from exc
    event = EnterpriseEvent.from_dict(payload)
    if settings.agent_runtime_mode == "adk":
        store.refresh()
        if store.has_processed_event(event.event_id):
            guided_demo.confirm_duplicate(event.event_id)
            return {"event_id": event.event_id, "status": "duplicate_ignored", "actions": []}
        if (
            event.event_type == "recall.issued"
            and engine.daily_workflow_count() >= settings.max_daily_workflows
        ):
            return {
                "event_id": event.event_id,
                "status": "daily_workflow_limit_reached",
                "actions": [],
            }
        result = await get_adk_runtime().run_event(event)
        engine.record_agent_processing(event, result)
        return {"event_id": event.event_id, **result}
    return engine.process(event)
