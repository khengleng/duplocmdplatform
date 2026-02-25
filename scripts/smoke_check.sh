#!/usr/bin/env sh
set -eu

: "${CMDB_BASE_URL:?CMDB_BASE_URL is required}"

BASE_URL="${CMDB_BASE_URL%/}"

HEALTH_CODE="$(curl -sS -o /tmp/cmdb_smoke_health.out -w '%{http_code}' "${BASE_URL}/health")"
if [ "${HEALTH_CODE}" != "200" ]; then
  echo "Smoke check failed: /health returned ${HEALTH_CODE}"
  cat /tmp/cmdb_smoke_health.out
  exit 1
fi

ALERTS_CODE="$(curl -sS -o /tmp/cmdb_smoke_alerts.out -w '%{http_code}' "${BASE_URL}/dashboard/alerts")"
if [ "${ALERTS_CODE}" != "401" ]; then
  echo "Smoke check failed: /dashboard/alerts without auth returned ${ALERTS_CODE}"
  cat /tmp/cmdb_smoke_alerts.out
  exit 1
fi

echo "Smoke checks passed for ${BASE_URL}"
