"""Bounded guided-demo controls for the public hackathon dashboard."""

from __future__ import annotations

import json
import secrets
import threading
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

from app.models import EnterpriseEvent
from app.store import StateStore

DEMO_STEP_NAMES = ("transfer", "recall", "late-arrival", "duplicate")


class GuidedDemoError(ValueError):
    """A safe, user-facing guided-demo validation error."""


class GuidedDemoController:
    """Expose only an ordered, rate-bounded synthetic scenario.

    The run ledger lives in a control collection that survives business-state resets. This
    prevents a public user from resetting the daily cost counter while keeping the canonical
    scenario repeatable.
    """

    def __init__(
        self,
        store: StateStore,
        scenario_path: Path,
        *,
        daily_limit: int,
        ttl_minutes: int,
    ):
        if daily_limit < 1 or ttl_minutes < 1:
            raise ValueError("Guided demo limits must be positive")
        self.store = store
        self.daily_limit = daily_limit
        self.ttl = timedelta(minutes=ttl_minutes)
        self.events = self._load_events(scenario_path)
        self._lock = threading.Lock()

    @staticmethod
    def _load_events(path: Path) -> tuple[EnterpriseEvent, ...]:
        events = tuple(
            EnterpriseEvent.from_dict(json.loads(line))
            for line in path.read_text(encoding="utf-8").splitlines()
            if line.strip()
        )
        if len(events) != len(DEMO_STEP_NAMES):
            raise ValueError("Guided demo requires exactly four scenario deliveries")
        if events[-1].event_id != events[-2].event_id:
            raise ValueError("Final guided-demo event must repeat the late-arrival event ID")
        return events

    def start(self, now: datetime | None = None) -> dict[str, Any]:
        current = now or datetime.now(UTC)
        with self._lock:
            self.store.refresh()
            runs = self.store.collection("demo_runs")
            self._expire_and_prune(runs, current)
            active = next(
                (
                    run
                    for run in self._ordered_runs(runs, newest_first=True)
                    if run.get("status") == "active"
                    and self._parse_time(run["expires_at"]) > current
                ),
                None,
            )
            if active is not None:
                return self._status(active, resumed=True)

            today = current.date().isoformat()
            if sum(run.get("day") == today for run in runs) >= self.daily_limit:
                raise GuidedDemoError("The public demo has reached today's safety limit")

            run = {
                "run_id": secrets.token_urlsafe(12),
                "day": today,
                "started_at": current.isoformat(),
                "expires_at": (current + self.ttl).isoformat(),
                "status": "active",
                "next_step": 0,
                "last_step": "",
                "duplicate_confirmed_at": "",
            }
            runs.append(run)
            self.store.flush()
            self.store.reset()
            return self._status(run, resumed=False)

    def prepare_step(
        self, run_id: str, step_name: str, now: datetime | None = None
    ) -> EnterpriseEvent:
        current = now or datetime.now(UTC)
        if step_name not in DEMO_STEP_NAMES:
            raise GuidedDemoError("Unknown guided-demo step")
        with self._lock:
            self.store.refresh()
            run = self._require_run(run_id, current)
            requested = DEMO_STEP_NAMES.index(step_name)
            expected = int(run.get("next_step", 0))
            if requested != expected:
                if expected >= len(DEMO_STEP_NAMES):
                    raise GuidedDemoError("All guided-demo steps have already been submitted")
                raise GuidedDemoError(f"Next guided-demo step is {DEMO_STEP_NAMES[expected]}")
            if requested > 0:
                previous = self.events[requested - 1]
                if not self.store.has_processed_event(previous.event_id):
                    raise GuidedDemoError("The previous agent workflow is still processing")

            run["next_step"] = requested + 1
            run["last_step"] = step_name
            run["last_published_at"] = current.isoformat()
            self.store.flush()
            return self.events[requested]

    def rollback_step(self, run_id: str, step_name: str) -> None:
        with self._lock:
            self.store.refresh()
            run = self.store.find_one("demo_runs", "run_id", run_id)
            if run is None or run.get("last_step") != step_name:
                return
            index = DEMO_STEP_NAMES.index(step_name)
            if int(run.get("next_step", 0)) == index + 1:
                run["next_step"] = index
                run["last_step"] = ""
                self.store.flush()

    def confirm_duplicate(self, event_id: str, now: datetime | None = None) -> None:
        if event_id != self.events[-1].event_id:
            return
        current = now or datetime.now(UTC)
        with self._lock:
            self.store.refresh()
            runs = self.store.collection("demo_runs")
            for run in self._ordered_runs(runs, newest_first=True):
                if (
                    run.get("status") == "active"
                    and int(run.get("next_step", 0)) == len(DEMO_STEP_NAMES)
                    and not run.get("duplicate_confirmed_at")
                ):
                    run["duplicate_confirmed_at"] = current.isoformat()
                    run["status"] = "completed"
                    self.store.flush()
                    return

    def status(self, run_id: str, now: datetime | None = None) -> dict[str, Any]:
        current = now or datetime.now(UTC)
        with self._lock:
            self.store.refresh()
            run = self._require_run(run_id, current, allow_completed=True)
            return self._status(run, resumed=True)

    def latest_status(self) -> dict[str, Any] | None:
        self.store.refresh()
        runs = self.store.collection("demo_runs")
        if not runs:
            return None
        latest = self._ordered_runs(runs, newest_first=True)[0]
        return self._status(latest, resumed=True)

    def _require_run(
        self,
        run_id: str,
        current: datetime,
        *,
        allow_completed: bool = False,
    ) -> dict[str, Any]:
        if not run_id:
            raise GuidedDemoError("Missing X-Demo-Run header")
        run = self.store.find_one("demo_runs", "run_id", run_id)
        if run is None:
            raise GuidedDemoError("Unknown guided-demo run")
        if self._parse_time(run["expires_at"]) <= current:
            run["status"] = "expired"
            self.store.flush()
            raise GuidedDemoError("This guided-demo run has expired")
        if run.get("status") != "active" and not allow_completed:
            raise GuidedDemoError("This guided-demo run is already complete")
        return run

    def _status(self, run: dict[str, Any], *, resumed: bool) -> dict[str, Any]:
        next_step = min(int(run.get("next_step", 0)), len(DEMO_STEP_NAMES))
        statuses = []
        for index, (name, event) in enumerate(zip(DEMO_STEP_NAMES, self.events, strict=True)):
            if name == "duplicate":
                completed = bool(run.get("duplicate_confirmed_at"))
            else:
                completed = self.store.has_processed_event(event.event_id)
            statuses.append(
                {
                    "name": name,
                    "event_id": event.event_id,
                    "event_type": event.event_type,
                    "completed": completed,
                    "available": (
                        run.get("status") == "active"
                        and index == next_step
                        and (
                            index == 0
                            or self.store.has_processed_event(self.events[index - 1].event_id)
                        )
                    ),
                }
            )
        return {
            "run_id": run["run_id"],
            "status": run.get("status", "active"),
            "resumed": resumed,
            "expires_at": run["expires_at"],
            "next_step": DEMO_STEP_NAMES[next_step] if next_step < len(DEMO_STEP_NAMES) else None,
            "steps": statuses,
        }

    def _expire_and_prune(self, runs: list[dict[str, Any]], current: datetime) -> None:
        cutoff = current - timedelta(days=30)
        runs[:] = [run for run in runs if self._parse_time(run["started_at"]) >= cutoff]
        for run in runs:
            if run.get("status") == "active" and self._parse_time(run["expires_at"]) <= current:
                run["status"] = "expired"

    @staticmethod
    def _parse_time(value: str) -> datetime:
        return datetime.fromisoformat(value.replace("Z", "+00:00"))

    @classmethod
    def _ordered_runs(
        cls,
        runs: list[dict[str, Any]],
        *,
        newest_first: bool,
    ) -> list[dict[str, Any]]:
        """Order the ledger explicitly; Firestore document streams are ID-ordered."""

        return sorted(
            runs,
            key=lambda run: cls._parse_time(run["started_at"]),
            reverse=newest_first,
        )
