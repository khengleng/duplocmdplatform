#!/usr/bin/env sh
set -eu

: "${RAILWAY_TOKEN:?RAILWAY_TOKEN is required}"
: "${RAILWAY_PROJECT_ID:?RAILWAY_PROJECT_ID is required}"
: "${RAILWAY_ENVIRONMENT:?RAILWAY_ENVIRONMENT is required}"
: "${RAILWAY_SERVICE:?RAILWAY_SERVICE is required}"

TIMEOUT_SECONDS="${RAILWAY_DEPLOY_TIMEOUT_SECONDS:-600}"
POLL_SECONDS="${RAILWAY_DEPLOY_POLL_SECONDS:-5}"
DEADLINE="$(($(date +%s) + TIMEOUT_SECONDS))"

while [ "$(date +%s)" -lt "${DEADLINE}" ]; do
  STATUS="$(
    railway service "${RAILWAY_SERVICE}" status \
      --project "${RAILWAY_PROJECT_ID}" \
      --environment "${RAILWAY_ENVIRONMENT}" | awk -F': ' '/Status:/{print $2}'
  )"

  case "${STATUS}" in
    SUCCESS)
      echo "Railway service ${RAILWAY_SERVICE} is SUCCESS"
      exit 0
      ;;
    FAILED|CRASHED|REMOVED)
      echo "Railway service ${RAILWAY_SERVICE} failed with status ${STATUS}"
      exit 1
      ;;
    *)
      echo "Waiting for ${RAILWAY_SERVICE}, current status: ${STATUS:-unknown}"
      sleep "${POLL_SECONDS}"
      ;;
  esac
done

echo "Timed out waiting for Railway service ${RAILWAY_SERVICE} after ${TIMEOUT_SECONDS}s"
exit 1
