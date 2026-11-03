#!/bin/sh
set -e

# Wait for Postgres when DATABASE_URL is set
if [ -n "${DATABASE_URL:-}" ]; then
  echo "Waiting for database..."
  python - <<'PY'
import os, sys, time
import dj_database_url

url = os.environ.get("DATABASE_URL", "")
cfg = dj_database_url.parse(url)
engine = cfg.get("ENGINE", "")
if "postgresql" not in engine and "postgres" not in engine:
    sys.exit(0)

import psycopg

host = cfg.get("HOST") or "localhost"
port = int(cfg.get("PORT") or 5432)
user = cfg.get("USER") or ""
password = cfg.get("PASSWORD") or ""
dbname = cfg.get("NAME") or ""

for attempt in range(60):
    try:
        with psycopg.connect(
            host=host,
            port=port,
            user=user,
            password=password,
            dbname=dbname,
            connect_timeout=3,
        ) as conn:
            conn.execute("SELECT 1")
        print("Database is ready.")
        sys.exit(0)
    except Exception as exc:
        print(f"DB not ready ({attempt + 1}/60): {exc}")
        time.sleep(1)
print("Database wait timed out.", file=sys.stderr)
sys.exit(1)
PY
fi

if [ "${RUN_MIGRATIONS:-true}" = "true" ]; then
  python manage.py migrate --noinput
fi

if [ -n "${DJANGO_SUPERUSER_EMAIL:-}" ] && [ -n "${DJANGO_SUPERUSER_PASSWORD:-}" ]; then
  python manage.py create_admin \
    --email "$DJANGO_SUPERUSER_EMAIL" \
    --password "$DJANGO_SUPERUSER_PASSWORD" \
    --name "${DJANGO_SUPERUSER_NAME:-Admin}" \
    2>/dev/null || true
fi

exec "$@"
