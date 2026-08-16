#!/usr/bin/env bash
set -euo pipefail

: "${GOOGLE_CLOUD_PROJECT:?Set GOOGLE_CLOUD_PROJECT}"
: "${CLOUD_RUN_REGION:=us-central1}"

gcloud run services update recallops-recall \
  --project="$GOOGLE_CLOUD_PROJECT" \
  --region="$CLOUD_RUN_REGION" \
  --update-env-vars=PUBLIC_DASHBOARD=true,ENABLE_PUBLIC_DEMO=true,PUBLIC_DEMO_DAILY_LIMIT=25,PUBLIC_DEMO_TTL_MINUTES=30

gcloud run services add-iam-policy-binding recallops-recall \
  --project="$GOOGLE_CLOUD_PROJECT" \
  --region="$CLOUD_RUN_REGION" \
  --member=allUsers \
  --role=roles/run.invoker

RECALL_URL="$(gcloud run services describe recallops-recall \
  --project="$GOOGLE_CLOUD_PROJECT" \
  --region="$CLOUD_RUN_REGION" \
  --format='value(status.url)')"

curl --fail --silent --show-error "$RECALL_URL/health"
echo
echo "Public guided RecallOps dashboard: $RECALL_URL"
