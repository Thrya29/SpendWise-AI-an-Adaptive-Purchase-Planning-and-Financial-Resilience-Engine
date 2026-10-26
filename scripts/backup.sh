#!/usr/bin/env bash
# Back up the PostgreSQL database to a compressed SQL file.
#
# Usage:  scripts/backup.sh [backup-dir]        (default: ./backups)
#         KEEP=30 scripts/backup.sh             (keep the newest 30; default 14)
# Cron:   15 2 * * *  cd /opt/spendwise && scripts/backup.sh >> backups/backup.log 2>&1
#
# Copy the files somewhere else too (another disk or cloud storage): a backup on the same
# server does not survive losing the server.
# $POSTGRES_* in single quotes is deliberate: it expands inside the db container.
# shellcheck disable=SC2016
set -euo pipefail
cd "$(dirname "$0")/.."

dir="${1:-backups}"
keep="${KEEP:-14}"
mkdir -p "$dir"
file="$dir/spendwise-$(date -u +%Y%m%dT%H%M%SZ).sql.gz"

docker compose exec -T db sh -c \
  'pg_dump --no-owner --no-privileges -U "$POSTGRES_USER" "$POSTGRES_DB"' \
  | gzip -9 > "$file.partial"
gzip -t "$file.partial"          # never keep a truncated or corrupt file
mv "$file.partial" "$file"

# Keep the newest $keep backups (names sort by time).
find "$dir" -maxdepth 1 -name 'spendwise-*.sql.gz' | sort -r | tail -n +"$((keep + 1))"   | xargs -r rm --
echo "$file"
