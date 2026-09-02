#!/bin/bash

set -euo pipefail

PROJECT_ID="${PROJECT_ID:-kamei-lab-budget}"
REGION="${REGION:-me-central1}"
SERVICE="${SERVICE:-kamei-lab-budget-web-staging}"
JOB="${JOB:-kamei-budget-sync}"

IMAGE="$({
  gcloud run services describe "$SERVICE" \
    --project="$PROJECT_ID" \
    --region="$REGION" \
    --format='value(spec.template.spec.containers[0].image)'
})"

if [[ -z "$IMAGE" ]]; then
  echo "Could not resolve the deployed image for $SERVICE." >&2
  exit 1
fi

gcloud run jobs update "$JOB" \
  --project="$PROJECT_ID" \
  --region="$REGION" \
  --image="$IMAGE" \
  --command=/cnb/lifecycle/launcher \
  --args=python,manage.py,sync_sheets

JOB_IMAGE="$({
  gcloud run jobs describe "$JOB" \
    --project="$PROJECT_ID" \
    --region="$REGION" \
    --format='value(spec.template.spec.template.spec.containers[0].image)'
})"

if [[ "$JOB_IMAGE" != "$IMAGE" ]]; then
  echo "Sync job image does not match the web service image." >&2
  exit 1
fi

echo "Aligned $JOB with $SERVICE at $IMAGE"
