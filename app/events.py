"""Google Pub/Sub transport adapters for enterprise events."""

from __future__ import annotations

import json
from collections.abc import Callable
from typing import Any

from app.models import EnterpriseEvent


class PubSubPublisher:
    def __init__(
        self,
        project: str,
        topic: str,
        *,
        client: Any | None = None,
    ):
        if not project or not topic:
            raise ValueError("Pub/Sub publisher requires project and topic")
        if client is None:
            try:
                from google.cloud import pubsub_v1
            except ImportError as exc:
                raise RuntimeError(
                    "Pub/Sub publishing requires `pip install -e \".[google]\"`"
                ) from exc
            client = pubsub_v1.PublisherClient()
        self.client = client
        self.topic_path = client.topic_path(project, topic)

    def publish(self, event: EnterpriseEvent) -> str:
        """Publish the documented event envelope and wait for its server message ID."""

        data = json.dumps(event.to_dict(), separators=(",", ":"), sort_keys=True).encode("utf-8")
        future = self.client.publish(
            self.topic_path,
            data,
            event_type=event.event_type,
            scenario_id=event.scenario_id,
        )
        return str(future.result(timeout=30))


def verify_pubsub_oidc(
    authorization: str | None,
    *,
    audience: str,
    expected_email: str,
    token_verifier: Callable[[str, str], dict[str, Any]] | None = None,
) -> dict[str, Any]:
    """Verify Pub/Sub's Google-signed JWT plus its audience and service-account identity."""

    if not audience or not expected_email:
        raise ValueError("PUBSUB_PUSH_AUDIENCE and PUBSUB_PUSH_SERVICE_ACCOUNT are required")
    scheme, separator, token = (authorization or "").partition(" ")
    if separator != " " or scheme.lower() != "bearer" or not token:
        raise PermissionError("Missing Pub/Sub bearer token")

    if token_verifier is None:
        try:
            from google.auth.transport import requests
            from google.oauth2 import id_token
        except ImportError as exc:
            raise RuntimeError(
                "Pub/Sub authentication requires `pip install -e \".[google]\"`"
            ) from exc

        def token_verifier(value: str, expected_audience: str) -> dict[str, Any]:
            return id_token.verify_oauth2_token(
                value, requests.Request(), audience=expected_audience
            )

    claims = token_verifier(token, audience)
    if claims.get("email") != expected_email or claims.get("email_verified") is not True:
        raise PermissionError("Unexpected or unverified Pub/Sub service account")
    return claims
