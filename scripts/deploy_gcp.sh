#!/usr/bin/env bash
set -euo pipefail

: "${GOOGLE_CLOUD_PROJECT:?Set GOOGLE_CLOUD_PROJECT}"
: "${CLOUD_RUN_REGION:=us-central1}"
: "${GOOGLE_CLOUD_LOCATION:=global}"
: "${AGENT_REGISTRY_LOCATION:=global}"
: "${ARTIFACT_REPOSITORY:=recallops}"
: "${IMAGE_TAG:=manual}"

IMAGE="${CLOUD_RUN_REGION}-docker.pkg.dev/${GOOGLE_CLOUD_PROJECT}/${ARTIFACT_REPOSITORY}/recallops:${IMAGE_TAG}"
COMMON_ENV="APP_ENV=production,STATE_BACKEND=firestore,GOOGLE_CLOUD_PROJECT=${GOOGLE_CLOUD_PROJECT},GOOGLE_CLOUD_LOCATION=${GOOGLE_CLOUD_LOCATION},AGENT_REGISTRY_LOCATION=${AGENT_REGISTRY_LOCATION},GOOGLE_GENAI_USE_VERTEXAI=true,FIRESTORE_DATABASE=(default),GEMINI_ROUTINE_MODEL=gemini-3.5-flash-lite,GEMINI_COMPLEX_MODEL=gemini-3.5-flash,MAX_MODEL_CALLS_PER_WORKFLOW=4,MAX_DAILY_WORKFLOWS=100,ENABLE_CLOUD_TRACE=true,PUBLIC_DASHBOARD=false,ENABLE_PUBLIC_DEMO=false,PUBLIC_DEMO_DAILY_LIMIT=25,PUBLIC_DEMO_TTL_MINUTES=30"

gcloud builds submit --tag="$IMAGE"

deploy_role() {
  role="$1"
  runtime_mode="$2"
  gcloud run deploy "recallops-${role}" \
    --image="$IMAGE" \
    --region="$CLOUD_RUN_REGION" \
    --service-account="recallops-${role}@${GOOGLE_CLOUD_PROJECT}.iam.gserviceaccount.com" \
    --cpu=1 \
    --memory=512Mi \
    --concurrency=8 \
    --timeout=300 \
    --min-instances=0 \
    --max-instances=1 \
    --cpu-throttling \
    --no-allow-unauthenticated \
    --set-env-vars="${COMMON_ENV},AGENT_ROLE=${role},AGENT_RUNTIME_MODE=${runtime_mode},PUBLIC_BASE_URL=https://pending.invalid"
}

deploy_role supply adk
deploy_role finance adk
deploy_role recall deterministic

RECALL_URL="$(gcloud run services describe recallops-recall --region="$CLOUD_RUN_REGION" --format='value(status.url)')"
SUPPLY_URL="$(gcloud run services describe recallops-supply --region="$CLOUD_RUN_REGION" --format='value(status.url)')"
FINANCE_URL="$(gcloud run services describe recallops-finance --region="$CLOUD_RUN_REGION" --format='value(status.url)')"

gcloud run services update recallops-supply \
  --region="$CLOUD_RUN_REGION" \
  --update-env-vars="PUBLIC_BASE_URL=${SUPPLY_URL}"
gcloud run services update recallops-finance \
  --region="$CLOUD_RUN_REGION" \
  --update-env-vars="PUBLIC_BASE_URL=${FINANCE_URL}"

CARD_DIR="$(mktemp -d)"
trap 'rm -rf "$CARD_DIR"' EXIT
python3 scripts/render_agent_cards.py \
  --output="$CARD_DIR" \
  --recall-url="$RECALL_URL" \
  --supply-url="$SUPPLY_URL" \
  --finance-url="$FINANCE_URL"
AGENT_CARD_DIR="$CARD_DIR" scripts/register_agents.sh

SUPPLY_RESOURCE="$(gcloud agent-registry services describe supply-agent --project="$GOOGLE_CLOUD_PROJECT" --location="$AGENT_REGISTRY_LOCATION" --format='value(registryResource)')"
FINANCE_RESOURCE="$(gcloud agent-registry services describe finance-agent --project="$GOOGLE_CLOUD_PROJECT" --location="$AGENT_REGISTRY_LOCATION" --format='value(registryResource)')"
if [[ -z "$SUPPLY_RESOURCE" || -z "$FINANCE_RESOURCE" ]]; then
  echo "Agent Registry did not return both specialist resource names." >&2
  exit 1
fi

RECALL_ACCOUNT="recallops-recall@${GOOGLE_CLOUD_PROJECT}.iam.gserviceaccount.com"
PUSH_ACCOUNT="recallops-pubsub-push@${GOOGLE_CLOUD_PROJECT}.iam.gserviceaccount.com"
gcloud run services add-iam-policy-binding recallops-supply \
  --region="$CLOUD_RUN_REGION" \
  --member="serviceAccount:${RECALL_ACCOUNT}" \
  --role=roles/run.invoker
gcloud run services add-iam-policy-binding recallops-finance \
  --region="$CLOUD_RUN_REGION" \
  --member="serviceAccount:${RECALL_ACCOUNT}" \
  --role=roles/run.invoker
gcloud run services add-iam-policy-binding recallops-recall \
  --region="$CLOUD_RUN_REGION" \
  --member="serviceAccount:${PUSH_ACCOUNT}" \
  --role=roles/run.invoker

PUSH_AUDIENCE="${RECALL_URL}/api/pubsub"
gcloud run services update recallops-recall \
  --region="$CLOUD_RUN_REGION" \
  --update-env-vars="PUBLIC_BASE_URL=${RECALL_URL},AGENT_RUNTIME_MODE=adk,SUPPLY_AGENT_RESOURCE=${SUPPLY_RESOURCE},FINANCE_AGENT_RESOURCE=${FINANCE_RESOURCE},PUBSUB_TOPIC=enterprise-events,PUBSUB_PUSH_AUDIENCE=${PUSH_AUDIENCE},PUBSUB_PUSH_SERVICE_ACCOUNT=${PUSH_ACCOUNT}"

if gcloud pubsub subscriptions describe recallops-recall-push >/dev/null 2>&1; then
  gcloud pubsub subscriptions modify-push-config recallops-recall-push \
    --push-endpoint="$PUSH_AUDIENCE" \
    --push-auth-service-account="$PUSH_ACCOUNT" \
    --push-auth-token-audience="$PUSH_AUDIENCE"
else
  gcloud pubsub subscriptions create recallops-recall-push \
    --topic=enterprise-events \
    --push-endpoint="$PUSH_AUDIENCE" \
    --push-auth-service-account="$PUSH_ACCOUNT" \
    --push-auth-token-audience="$PUSH_AUDIENCE" \
    --ack-deadline=300 \
    --message-retention-duration=1d
fi

echo "Recall URL: $RECALL_URL"
echo "Supply URL: $SUPPLY_URL"
echo "Finance URL: $FINANCE_URL"
