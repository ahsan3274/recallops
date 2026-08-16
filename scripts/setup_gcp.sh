#!/usr/bin/env bash
set -euo pipefail

: "${GOOGLE_CLOUD_PROJECT:?Set GOOGLE_CLOUD_PROJECT to a billing-enabled project}"
: "${CLOUD_RUN_REGION:=us-central1}"
: "${FIRESTORE_LOCATION:=$CLOUD_RUN_REGION}"
: "${ARTIFACT_REPOSITORY:=recallops}"

gcloud config set project "$GOOGLE_CLOUD_PROJECT"
gcloud services enable \
  run.googleapis.com \
  cloudbuild.googleapis.com \
  artifactregistry.googleapis.com \
  firestore.googleapis.com \
  pubsub.googleapis.com \
  aiplatform.googleapis.com \
  agentregistry.googleapis.com \
  cloudtrace.googleapis.com \
  telemetry.googleapis.com

if ! gcloud artifacts repositories describe "$ARTIFACT_REPOSITORY" \
  --location="$CLOUD_RUN_REGION" >/dev/null 2>&1; then
  gcloud artifacts repositories create "$ARTIFACT_REPOSITORY" \
    --location="$CLOUD_RUN_REGION" \
    --repository-format=docker \
    --description="RecallOps single-image repository"
fi

if ! gcloud firestore databases describe --database='(default)' >/dev/null 2>&1; then
  gcloud firestore databases create \
    --database='(default)' \
    --location="$FIRESTORE_LOCATION" \
    --type=firestore-native \
    --edition=standard
fi

if ! gcloud pubsub topics describe enterprise-events >/dev/null 2>&1; then
  gcloud pubsub topics create enterprise-events
fi

for role in recall supply finance; do
  account="recallops-${role}"
  email="${account}@${GOOGLE_CLOUD_PROJECT}.iam.gserviceaccount.com"
  if ! gcloud iam service-accounts describe "$email" >/dev/null 2>&1; then
    gcloud iam service-accounts create "$account" --display-name="RecallOps ${role} agent"
  fi
  for iam_role in \
    roles/datastore.user \
    roles/aiplatform.user \
    roles/logging.logWriter \
    roles/cloudtrace.agent \
    roles/serviceusage.serviceUsageConsumer; do
    gcloud projects add-iam-policy-binding "$GOOGLE_CLOUD_PROJECT" \
      --member="serviceAccount:${email}" \
      --role="$iam_role" >/dev/null
  done
done

RECALL_ACCOUNT="recallops-recall@${GOOGLE_CLOUD_PROJECT}.iam.gserviceaccount.com"
gcloud projects add-iam-policy-binding "$GOOGLE_CLOUD_PROJECT" \
  --member="serviceAccount:${RECALL_ACCOUNT}" \
  --role=roles/agentregistry.viewer >/dev/null
gcloud pubsub topics add-iam-policy-binding enterprise-events \
  --member="serviceAccount:${RECALL_ACCOUNT}" \
  --role=roles/pubsub.publisher >/dev/null

PUSH_ACCOUNT="recallops-pubsub-push@${GOOGLE_CLOUD_PROJECT}.iam.gserviceaccount.com"
if ! gcloud iam service-accounts describe "$PUSH_ACCOUNT" >/dev/null 2>&1; then
  gcloud iam service-accounts create recallops-pubsub-push \
    --display-name="RecallOps authenticated Pub/Sub push"
fi

PROJECT_NUMBER="$(gcloud projects describe "$GOOGLE_CLOUD_PROJECT" --format='value(projectNumber)')"
PUBSUB_SERVICE_AGENT="service-${PROJECT_NUMBER}@gcp-sa-pubsub.iam.gserviceaccount.com"
gcloud iam service-accounts add-iam-policy-binding "$PUSH_ACCOUNT" \
  --member="serviceAccount:${PUBSUB_SERVICE_AGENT}" \
  --role=roles/iam.serviceAccountTokenCreator >/dev/null

echo "Google Cloud prerequisites are ready. Review the README deployment section before running deploy_gcp.sh."
