# Forfaitify Backend

Django + DRF API for the Forfaitify verified invoice-financing marketplace.

## Stack

- Django 5.2 / DRF / SimpleJWT / Channels (WebSocket) / Celery
- Apps by domain: `accounts`, `kyc`, `balances`, `payments`, `pools`, `epochs`, `invoices`, `cosign`, `notifications`, `support`, `admin_ops`
- External integrations in `utils/` (Supabase Auth, Didit KYB/KYC, payments dummy, DocuSign stub)
- Live updates: WebSocket `ws/live/` sends **invalidate** keys (clients pull REST)
- Email: branded templates for money / co-sign / investment via Celery (rate-limited). Set `EMAIL_BACKEND=zoho_cpaas` plus `ZOHO_CPAAS_API_KEY` to send through Zoho CPaaS (`POST /v1.1/email`).

## Quick start (Docker — recommended)

```bash
cd ForfaitifyBackend
cp .env.example .env
# optional: set DJANGO_SUPERUSER_EMAIL / DJANGO_SUPERUSER_PASSWORD in .env
docker compose up --build
```

Services:

| Service | Role |
|---------|------|
| `api` | ASGI (HTTP + WebSocket) on `:8000` |
| `worker` | Celery email worker |
| `redis` | Channels + Celery broker |
| `db` | Postgres 16 |

API: `http://127.0.0.1:8000/api/v1/`  
Live socket: `ws://127.0.0.1:8000/ws/live/?token=<access_jwt>`

Hot-reload bind mount:

```bash
docker compose -f docker-compose.yml -f docker-compose.dev.yml up --build
```

Stop / wipe DB volume:

```bash
docker compose down
docker compose down -v   # also remove Postgres + media volumes
```

Point the Vite app at the container (`VITE_API_BASE_URL=http://127.0.0.1:8000/api/v1`, `VITE_WS_BASE_URL=ws://127.0.0.1:8000`).

## Quick start (local venv)

```bash
cd ForfaitifyBackend
source env/bin/activate
pip install -r requirements.txt
cp .env.example .env
python manage.py migrate
python manage.py create_admin --email admin@forfaitify.com --password 'ChangeMe123!' --name Admin
```

### HTTP + WebSocket (ASGI)

```bash
uvicorn ForfaitifyApiCore.asgi:application --reload --host 127.0.0.1 --port 8000
```

### Celery (email)

With `CELERY_TASK_ALWAYS_EAGER=True` (default in `.env.example`), email tasks run in-process.

For a real worker (set `REDIS_URL` and `CELERY_TASK_ALWAYS_EAGER=False`):

```bash
redis-server
celery -A ForfaitifyApiCore worker -l info
```

Email verification and password reset use a local 6-digit code sent through the configured mail provider (`EMAIL_BACKEND=zoho_cpaas` uses Zoho CPaaS). Signing in with the right password before the email is verified returns `email_unverified`; the app then sends a new code.

## Auth smoke test

```bash
# Register merchant
curl -s -X POST http://127.0.0.1:8000/api/v1/auth/register \
  -H 'Content-Type: application/json' \
  -d '{"email":"m@example.com","password":"password12","full_name":"Merchant One","country":"Nigeria","phone":"+234","date_of_birth":"1990-01-01","role":"merchant"}'

# Verify
curl -s -X POST http://127.0.0.1:8000/api/v1/auth/verify-email \
  -H 'Content-Type: application/json' \
  -d '{"email":"m@example.com","otp":"123456"}'
```

## Live events

Domain code calls `notifications.emit.emit(...)` after mutations. That:

1. Creates an in-app `Notification` (prefs-aware)
2. Publishes WebSocket `invalidate` (+ optional `notification.created`)
3. Enqueues Celery email for money / cosign / investment only

## Jobs

```bash
python manage.py roll_epochs
```

## Phases

1. Accounts + OTP (Supabase util / stub)
2. KYB/KYC (Didit hosted session + admin approval; no documents stored)
3. Payments + Balance (NGN; `PAYMENT_PROCESSOR=dummy` demo or `flutterwave` stub; admin-approve then transfer; auto-repay)
4. Pools, epochs, invoices, financing
5. Co-sign (DocuSign util)
6. Notifications, support, fees, gateways, staff
7. Live WebSocket + Celery email
