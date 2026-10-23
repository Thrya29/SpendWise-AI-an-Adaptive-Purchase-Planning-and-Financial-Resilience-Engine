#!/bin/sh
set -e
if [ "${SPENDWISE_RUN_MIGRATIONS:-true}" = "true" ]; then
  echo "Applying database migrations..."
  alembic upgrade head
fi
exec "$@"
