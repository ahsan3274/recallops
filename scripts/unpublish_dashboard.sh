#!/usr/bin/env bash
set -euo pipefail

: "${GOOGLE_CLOUD_PROJECT:?Set GOOGLE_CLOUD_PROJECT}"
: "${CLOUD_RUN_REGION:=us-central1}"

gcloud run services remove-iam-policy-binding recallops-recall \
  --project="$GOOGLE_CLOUD_PROJECT" \
  --region="$CLOUD_RUN_REGION" \
  --member=allUsers \
  --role=roles/run.invoker

gcloud run services update recallops-recall \
  --project="$GOOGLE_CLOUD_PROJECT" \
  --region="$CLOUD_RUN_REGION" \
  --update-env-vars=PUBLIC_DASHBOARD=false,ENABLE_PUBLIC_DEMO=false

echo "RecallOps dashboard is private."
