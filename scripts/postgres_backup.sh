#!/usr/bin/env sh
set -eu

: "${DATABASE_URL:?DATABASE_URL is required}"

STAMP="$(date -u +%Y%m%dT%H%M%SZ)"
OUTFILE="${1:-backups/cmdb_${STAMP}.sql.gz}"

mkdir -p "$(dirname "${OUTFILE}")"
pg_dump --no-owner --no-privileges "$DATABASE_URL" | gzip >"${OUTFILE}"
echo "Backup written to ${OUTFILE}"
