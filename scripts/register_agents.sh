#!/usr/bin/env bash
set -euo pipefail

: "${GOOGLE_CLOUD_PROJECT:?Set GOOGLE_CLOUD_PROJECT}"
: "${AGENT_REGISTRY_LOCATION:=global}"
: "${AGENT_CARD_DIR:=agent_cards}"

for agent in recall-agent supply-agent finance-agent; do
  if gcloud agent-registry services describe "$agent" \
    --project="$GOOGLE_CLOUD_PROJECT" \
    --location="$AGENT_REGISTRY_LOCATION" >/dev/null 2>&1; then
    gcloud agent-registry services update "$agent" \
      --project="$GOOGLE_CLOUD_PROJECT" \
      --location="$AGENT_REGISTRY_LOCATION" \
      --display-name="$agent" \
      --agent-spec-type=a2a-agent-card \
      --agent-spec-content="$AGENT_CARD_DIR/$agent.json"
  else
    gcloud agent-registry services create "$agent" \
      --project="$GOOGLE_CLOUD_PROJECT" \
      --location="$AGENT_REGISTRY_LOCATION" \
      --display-name="$agent" \
      --agent-spec-type=a2a-agent-card \
      --agent-spec-content="$AGENT_CARD_DIR/$agent.json"
  fi
done

gcloud agent-registry agents list \
  --project="$GOOGLE_CLOUD_PROJECT" \
  --location="$AGENT_REGISTRY_LOCATION"
