#!/usr/bin/env sh
set -eu

: "${DATABASE_URL:?DATABASE_URL is required}"
: "${RESTORE_CHECK_DATABASE_URL:?RESTORE_CHECK_DATABASE_URL is required}"

TMP_DUMP="$(mktemp)"
trap 'rm -f "${TMP_DUMP}"' EXIT

pg_dump --no-owner --no-privileges "$DATABASE_URL" >"${TMP_DUMP}"

psql "$RESTORE_CHECK_DATABASE_URL" -v ON_ERROR_STOP=1 <<'SQL'
DROP SCHEMA IF EXISTS public CASCADE;
CREATE SCHEMA public;
SQL

psql "$RESTORE_CHECK_DATABASE_URL" -v ON_ERROR_STOP=1 -f "${TMP_DUMP}" >/dev/null

SOURCE_CI_COUNT="$(psql "$DATABASE_URL" -Atqc 'SELECT count(*) FROM cis')"
RESTORE_CI_COUNT="$(psql "$RESTORE_CHECK_DATABASE_URL" -Atqc 'SELECT count(*) FROM cis')"

if [ "${SOURCE_CI_COUNT}" != "${RESTORE_CI_COUNT}" ]; then
  echo "Restore check failed: source ci count=${SOURCE_CI_COUNT}, restore ci count=${RESTORE_CI_COUNT}"
  exit 1
fi

echo "Restore check passed: ci count=${RESTORE_CI_COUNT}"
