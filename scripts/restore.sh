#!/usr/bin/env bash
# Restore a backup made by scripts/backup.sh.
#
# Usage:  scripts/restore.sh FILE --yes            replace the live database (stops api + worker)
#         scripts/restore.sh FILE --into NAME      load into a separate database to inspect it
# $POSTGRES_* in single quotes is deliberate: it expands inside the db container.
# shellcheck disable=SC2016
set -euo pipefail
cd "$(dirname "$0")/.."

file="${1:?usage: scripts/restore.sh FILE (--yes | --into NAME)}"
shift
target=""
confirmed=0
while [ $# -gt 0 ]; do
  case "$1" in
    --into) target="${2:?--into needs a database name}"; shift 2 ;;
    --yes) confirmed=1; shift ;;
    *) echo "unknown option: $1" >&2; exit 2 ;;
  esac
done
gzip -t "$file"

load() {  # $1 = database name
  gunzip -c "$file" | docker compose exec -T db sh -c \
    "psql -v ON_ERROR_STOP=1 --quiet -U \"\$POSTGRES_USER\" -d '$1'" > /dev/null
}

if [ -n "$target" ]; then
  case "$target" in *[!a-zA-Z0-9_]*) echo "database name must be letters, digits or _" >&2; exit 2 ;; esac
  docker compose exec -T db sh -c "createdb -U \"\$POSTGRES_USER\" '$target'"
  load "$target"
  echo "Restored into database '$target'."
  exit 0
fi

if [ "$confirmed" -ne 1 ]; then
  echo "This replaces ALL current data with $file. Re-run with --yes to continue." >&2
  exit 1
fi
docker compose stop api worker
docker compose exec -T db sh -c \
  'dropdb -U "$POSTGRES_USER" --if-exists "$POSTGRES_DB" && createdb -U "$POSTGRES_USER" "$POSTGRES_DB"'
db_name=$(docker compose exec -T db sh -c 'printf %s "$POSTGRES_DB"')
load "$db_name"
docker compose start api worker
echo "Restored $file. The API applies any newer migrations as it starts."
