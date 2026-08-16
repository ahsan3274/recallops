from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any


@dataclass(frozen=True)
class EnterpriseEvent:
    event_id: str
    event_type: str
    occurred_at: str
    source: str
    scenario_id: str
    payload: dict[str, Any] = field(default_factory=dict)

    @classmethod
    def from_dict(cls, value: dict[str, Any]) -> "EnterpriseEvent":
        required = {"event_id", "event_type", "occurred_at", "source", "scenario_id"}
        missing = required.difference(value)
        if missing:
            raise ValueError(f"Missing event fields: {', '.join(sorted(missing))}")
        return cls(
            event_id=str(value["event_id"]),
            event_type=str(value["event_type"]),
            occurred_at=str(value["occurred_at"]),
            source=str(value["source"]),
            scenario_id=str(value["scenario_id"]),
            payload=dict(value.get("payload", {})),
        )

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)
