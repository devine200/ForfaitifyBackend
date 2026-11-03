"""Django settings for ForfaitifyApiCore."""

from datetime import timedelta
from pathlib import Path
import os

from dotenv import load_dotenv

load_dotenv()

BASE_DIR = Path(__file__).resolve().parent.parent

SECRET_KEY = os.getenv(
    "DJANGO_SECRET_KEY",
    "django-insecure-dev-only-change-me-forfaitify",
)
DEBUG = os.getenv("DJANGO_DEBUG", "True").lower() in ("1", "true", "yes")
ALLOWED_HOSTS = [
    h.strip()
    for h in os.getenv(
        "DJANGO_ALLOWED_HOSTS",
        "localhost,127.0.0.1,testserver",
    ).split(",")
    if h.strip()
]

INSTALLED_APPS = [
    "django.contrib.admin",
    "django.contrib.auth",
    "django.contrib.contenttypes",
    "django.contrib.sessions",
    "django.contrib.messages",
    "django.contrib.staticfiles",
    # Third party
    "corsheaders",
    "rest_framework",
    "rest_framework_simplejwt",
    "rest_framework_simplejwt.token_blacklist",
    "channels",
    # Local
    "common",
    "accounts",
    "kyc",
    "balances",
    "payments",
    "pools",
    "epochs",
    "invoices",
    "cosign",
    "notifications",
    "support",
    "admin_ops",
]

MIDDLEWARE = [
    "django.middleware.security.SecurityMiddleware",
    "corsheaders.middleware.CorsMiddleware",
    "django.contrib.sessions.middleware.SessionMiddleware",
    "django.middleware.common.CommonMiddleware",
    "django.middleware.csrf.CsrfViewMiddleware",
    "django.contrib.auth.middleware.AuthenticationMiddleware",
    "django.contrib.messages.middleware.MessageMiddleware",
    "django.middleware.clickjacking.XFrameOptionsMiddleware",
]

ROOT_URLCONF = "ForfaitifyApiCore.urls"

TEMPLATES = [
    {
        "BACKEND": "django.template.backends.django.DjangoTemplates",
        "DIRS": [],
        "APP_DIRS": True,
        "OPTIONS": {
            "context_processors": [
                "django.template.context_processors.request",
                "django.contrib.auth.context_processors.auth",
                "django.contrib.messages.context_processors.messages",
            ],
        },
    },
]

WSGI_APPLICATION = "ForfaitifyApiCore.wsgi.application"
ASGI_APPLICATION = "ForfaitifyApiCore.asgi.application"

# SQLite by default; set DATABASE_URL for Postgres (Docker / production).
_DATABASE_URL = os.getenv("DATABASE_URL", "").strip()
if _DATABASE_URL:
    import dj_database_url

    DATABASES = {
        "default": dj_database_url.parse(
            _DATABASE_URL,
            conn_max_age=int(os.getenv("DB_CONN_MAX_AGE", "60")),
        )
    }
else:
    _sqlite = os.getenv("SQLITE_PATH", str(BASE_DIR / "db.sqlite3"))
    DATABASES = {
        "default": {
            "ENGINE": "django.db.backends.sqlite3",
            "NAME": _sqlite,
        }
    }

AUTH_USER_MODEL = "accounts.User"

AUTH_PASSWORD_VALIDATORS = [
    {"NAME": "django.contrib.auth.password_validation.UserAttributeSimilarityValidator"},
    {"NAME": "django.contrib.auth.password_validation.MinimumLengthValidator"},
    {"NAME": "django.contrib.auth.password_validation.CommonPasswordValidator"},
    {"NAME": "django.contrib.auth.password_validation.NumericPasswordValidator"},
]

LANGUAGE_CODE = "en-us"
TIME_ZONE = "UTC"
USE_I18N = True
USE_TZ = True

STATIC_URL = "static/"
MEDIA_URL = "/media/"
MEDIA_ROOT = BASE_DIR / "media"

DEFAULT_AUTO_FIELD = "django.db.models.BigAutoField"

CORS_ALLOWED_ORIGINS = [
    o.strip()
    for o in os.getenv(
        "CORS_ALLOWED_ORIGINS",
        "http://localhost:5173,http://127.0.0.1:5173",
    ).split(",")
    if o.strip()
]
CORS_ALLOW_CREDENTIALS = True

REST_FRAMEWORK = {
    "DEFAULT_AUTHENTICATION_CLASSES": (
        "rest_framework_simplejwt.authentication.JWTAuthentication",
    ),
    "DEFAULT_PERMISSION_CLASSES": (
        "rest_framework.permissions.IsAuthenticated",
    ),
    "DEFAULT_PAGINATION_CLASS": "common.pagination.StandardPagination",
    "PAGE_SIZE": 20,
    "DEFAULT_RENDERER_CLASSES": (
        "rest_framework.renderers.JSONRenderer",
    ),
    "EXCEPTION_HANDLER": "common.exceptions.api_exception_handler",
}

SIMPLE_JWT = {
    "ACCESS_TOKEN_LIFETIME": timedelta(minutes=60),
    "REFRESH_TOKEN_LIFETIME": timedelta(days=7),
    "ROTATE_REFRESH_TOKENS": True,
    "BLACKLIST_AFTER_ROTATION": True,
    "UPDATE_LAST_LOGIN": True,
}

# External integrations
SUPABASE_URL = os.getenv("SUPABASE_URL", "")
SUPABASE_ANON_KEY = os.getenv("SUPABASE_ANON_KEY", "")
SUPABASE_SERVICE_ROLE_KEY = os.getenv("SUPABASE_SERVICE_ROLE_KEY", "")
SUPABASE_JWT_SECRET = os.getenv("SUPABASE_JWT_SECRET", "")
AUTH_STUB_MODE = os.getenv("AUTH_STUB_MODE", "True").lower() in ("1", "true", "yes")

# live uses the live Didit application. test uses the sandbox application.
_didit_mode = os.getenv("DIDIT_MODE", "test").strip().lower()
DIDIT_MODE = "live" if _didit_mode == "live" else "test"
if DIDIT_MODE == "live":
    DIDIT_API_KEY = os.getenv("DIDIT_API_KEY", "")
    DIDIT_KYB_WORKFLOW_ID = os.getenv("DIDIT_KYB_WORKFLOW_ID", "")
    DIDIT_KYC_WORKFLOW_ID = os.getenv("DIDIT_KYC_WORKFLOW_ID", "")
    DIDIT_WEBHOOK_SECRET = os.getenv("DIDIT_WEBHOOK_SECRET", "")
    DIDIT_SANDBOX_SCENARIO = ""
else:
    DIDIT_API_KEY = os.getenv("DIDIT_TEST_API_KEY", "")
    DIDIT_KYB_WORKFLOW_ID = os.getenv("DIDIT_TEST_KYB_WORKFLOW_ID", "")
    DIDIT_KYC_WORKFLOW_ID = os.getenv("DIDIT_TEST_KYC_WORKFLOW_ID", "")
    DIDIT_WEBHOOK_SECRET = os.getenv("DIDIT_TEST_WEBHOOK_SECRET", "")
    DIDIT_SANDBOX_SCENARIO = os.getenv("DIDIT_SANDBOX_SCENARIO", "").strip()

PAYMENT_PROCESSOR = os.getenv("PAYMENT_PROCESSOR", "dummy")
PAYMENT_WEBHOOK_SECRET = os.getenv("PAYMENT_WEBHOOK_SECRET", "")
FLUTTERWAVE_SECRET_KEY = os.getenv("FLUTTERWAVE_SECRET_KEY", "")
FLUTTERWAVE_PUBLIC_KEY = os.getenv("FLUTTERWAVE_PUBLIC_KEY", "")
FLUTTERWAVE_WEBHOOK_HASH = os.getenv("FLUTTERWAVE_WEBHOOK_HASH", "")
FLUTTERWAVE_BASE_URL = os.getenv(
    "FLUTTERWAVE_BASE_URL", "https://api.flutterwave.com/v3"
).rstrip("/")

DOCUSIGN_INTEGRATION_KEY = os.getenv("DOCUSIGN_INTEGRATION_KEY", "")
DOCUSIGN_USER_ID = os.getenv("DOCUSIGN_USER_ID", "")
DOCUSIGN_ACCOUNT_ID = os.getenv("DOCUSIGN_ACCOUNT_ID", "")
DOCUSIGN_BASE_URL = os.getenv("DOCUSIGN_BASE_URL", "")
DOCUSIGN_WEBHOOK_SECRET = os.getenv("DOCUSIGN_WEBHOOK_SECRET", "")

DEFAULT_CURRENCY = os.getenv("DEFAULT_CURRENCY", "NGN").upper()

FRONTEND_BASE_URL = os.getenv("FRONTEND_BASE_URL", "http://localhost:5173")
REDIS_URL = os.getenv("REDIS_URL", "").strip()

# Email (transactional; Celery worker sends)
# EMAIL_BACKEND=zoho_cpaas selects the Zoho CPaaS HTTP API. Django still needs a
# real mail backend class, so that alias is mapped to the console backend.
_email_backend = os.getenv(
    "EMAIL_BACKEND",
    "django.core.mail.backends.console.EmailBackend",
).strip()
EMAIL_PROVIDER = os.getenv("EMAIL_PROVIDER", "").strip().lower()
if _email_backend.lower() in ("zoho_cpaas", "zoho"):
    EMAIL_PROVIDER = "zoho_cpaas"
    EMAIL_BACKEND = "django.core.mail.backends.console.EmailBackend"
else:
    EMAIL_BACKEND = _email_backend

ZOHO_CPAAS_API_KEY = os.getenv("ZOHO_CPAAS_API_KEY", "").strip()
ZOHO_CPAAS_BASE_URL = os.getenv("ZOHO_CPAAS_BASE_URL", "https://cpaas.zoho.com").rstrip("/")
DEFAULT_FROM_EMAIL = os.getenv("DEFAULT_FROM_EMAIL", "Forfaitify <noreply@forfaitify.com>")
EMAIL_HOST = os.getenv("EMAIL_HOST", "")
EMAIL_PORT = int(os.getenv("EMAIL_PORT", "587") or 587)
EMAIL_HOST_USER = os.getenv("EMAIL_HOST_USER", "")
EMAIL_HOST_PASSWORD = os.getenv("EMAIL_HOST_PASSWORD", "")
EMAIL_USE_TLS = os.getenv("EMAIL_USE_TLS", "True").lower() in ("1", "true", "yes")

EMAIL_RATE_PER_USER_HOUR = int(os.getenv("EMAIL_RATE_PER_USER_HOUR", "10"))
EMAIL_RATE_PER_USER_DAY = int(os.getenv("EMAIL_RATE_PER_USER_DAY", "30"))
EMAIL_SEND_TASK_RATE = os.getenv("EMAIL_SEND_TASK_RATE", "30/m")
EMAIL_CIRCUIT_FAILURE_THRESHOLD = int(os.getenv("EMAIL_CIRCUIT_FAILURE_THRESHOLD", "10"))
EMAIL_CIRCUIT_COOLDOWN_SECONDS = int(os.getenv("EMAIL_CIRCUIT_COOLDOWN_SECONDS", "120"))
EMAIL_IDEMPOTENCY_TTL_SECONDS = int(os.getenv("EMAIL_IDEMPOTENCY_TTL_SECONDS", "86400"))

if REDIS_URL:
    CACHES = {
        "default": {
            "BACKEND": "django.core.cache.backends.redis.RedisCache",
            "LOCATION": REDIS_URL,
        }
    }
    CHANNEL_LAYERS = {
        "default": {
            "BACKEND": "channels_redis.core.RedisChannelLayer",
            "CONFIG": {"hosts": [REDIS_URL]},
        }
    }
    CELERY_BROKER_URL = REDIS_URL
    CELERY_RESULT_BACKEND = REDIS_URL
else:
    CACHES = {
        "default": {
            "BACKEND": "django.core.cache.backends.locmem.LocMemCache",
            "LOCATION": "forfaitify",
        }
    }
    CHANNEL_LAYERS = {
        "default": {
            "BACKEND": "channels.layers.InMemoryChannelLayer",
        }
    }
    CELERY_BROKER_URL = os.getenv("CELERY_BROKER_URL", "memory://")
    CELERY_RESULT_BACKEND = os.getenv("CELERY_RESULT_BACKEND", "cache+memory://")

CELERY_TASK_ALWAYS_EAGER = os.getenv("CELERY_TASK_ALWAYS_EAGER", "False").lower() in (
    "1",
    "true",
    "yes",
)
CELERY_TASK_EAGER_PROPAGATES = True
CELERY_ACCEPT_CONTENT = ["json"]
CELERY_TASK_SERIALIZER = "json"
CELERY_RESULT_SERIALIZER = "json"
CELERY_TIMEZONE = TIME_ZONE
CELERY_BEAT_SCHEDULE = {
    "auto-repay-due-invoices": {
        "task": "invoices.tasks.sweep_auto_repayments",
        "schedule": 3600.0,  # hourly
    },
}
