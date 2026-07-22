import os
from pathlib import Path

import dj_database_url
from django.core.exceptions import ImproperlyConfigured


BASE_DIR = Path(__file__).resolve().parent.parent
SECRET_KEY = os.environ.get("SECRET_KEY", "local-development-only-change-me")
IS_CLOUD_RUN = bool(os.environ.get("K_SERVICE", "").strip())
BUILD_STATIC = os.environ.get("BUILD_STATIC", "false").strip().lower() in {
    "1",
    "true",
    "yes",
}
DEBUG = os.environ.get("DEBUG", "false" if IS_CLOUD_RUN else "true").strip().lower() in {
    "1",
    "true",
    "yes",
}
if IS_CLOUD_RUN and DEBUG:
    raise ImproperlyConfigured("DEBUG cannot be enabled on Cloud Run.")
ALLOWED_HOSTS = [
    host.strip()
    for host in os.environ.get("ALLOWED_HOSTS", "localhost,127.0.0.1,testserver").split(",")
    if host.strip()
]
CSRF_TRUSTED_ORIGINS = [
    origin.strip()
    for origin in os.environ.get("CSRF_TRUSTED_ORIGINS", "").split(",")
    if origin.strip()
]

INSTALLED_APPS = [
    "django.contrib.admin",
    "django.contrib.auth",
    "django.contrib.contenttypes",
    "django.contrib.sessions",
    "django.contrib.messages",
    "django.contrib.staticfiles",
    "django.contrib.humanize",
    "budget.apps.BudgetConfig",
    "labapps.apps.LabAppsConfig",
]

MIDDLEWARE = [
    "django.middleware.security.SecurityMiddleware",
    "django.contrib.sessions.middleware.SessionMiddleware",
    "django.middleware.common.CommonMiddleware",
    "django.middleware.csrf.CsrfViewMiddleware",
    "django.contrib.auth.middleware.AuthenticationMiddleware",
    "budget.middleware.IAPAuthenticationMiddleware",
    "django.contrib.messages.middleware.MessageMiddleware",
    "django.middleware.clickjacking.XFrameOptionsMiddleware",
]
if not DEBUG:
    MIDDLEWARE.insert(1, "whitenoise.middleware.WhiteNoiseMiddleware")

ROOT_URLCONF = "config.urls"
TEMPLATES = [
    {
        "BACKEND": "django.template.backends.django.DjangoTemplates",
        "DIRS": [BASE_DIR / "templates"],
        "APP_DIRS": True,
        "OPTIONS": {
            "context_processors": [
                "django.template.context_processors.request",
                "django.contrib.auth.context_processors.auth",
                "django.contrib.messages.context_processors.messages",
                "budget.context_processors.lab_context",
                "labapps.context_processors.lab_apps_context",
            ],
        },
    },
]

WSGI_APPLICATION = "config.wsgi.application"
ASGI_APPLICATION = "config.asgi.application"

database_url = (
    os.environ.get("CLOUD_DATABASE_URL", "").strip()
    or os.environ.get("DATABASE_URL", "").strip()
)
if not DEBUG and not database_url:
    raise ImproperlyConfigured(
        "CLOUD_DATABASE_URL or DATABASE_URL is required outside DEBUG mode."
    )
DATABASES = {
    "default": dj_database_url.parse(
        database_url or f"sqlite:///{BASE_DIR / 'db.sqlite3'}",
        conn_max_age=600,
        conn_health_checks=True,
    )
}

AUTH_PASSWORD_VALIDATORS = []
LANGUAGE_CODE = "en-us"
TIME_ZONE = "Asia/Dubai"
USE_I18N = True
USE_TZ = True

STATIC_URL = "static/"
STATIC_ROOT = BASE_DIR / "staticfiles"
MEDIA_ROOT = Path(os.environ.get("MEDIA_ROOT", BASE_DIR / "media"))
INVOICE_BUCKET = os.environ.get("INVOICE_BUCKET", "").strip()
INVOICE_STORAGE_PREFIX = os.environ.get("INVOICE_STORAGE_PREFIX", "invoices").strip("/")
KNOWLEDGE_BUCKET = os.environ.get("KNOWLEDGE_BUCKET", INVOICE_BUCKET).strip()
KNOWLEDGE_STORAGE_PREFIX = os.environ.get(
    "KNOWLEDGE_STORAGE_PREFIX", "knowledge"
).strip("/")
KNOWLEDGE_SEED_OBJECT = os.environ.get(
    "KNOWLEDGE_SEED_OBJECT", "knowledge-seed/records.json"
).strip("/")
STORAGES = {
    "default": {"BACKEND": "django.core.files.storage.FileSystemStorage"},
    "staticfiles": {
        "BACKEND": (
            "django.contrib.staticfiles.storage.StaticFilesStorage"
            if DEBUG
            else "whitenoise.storage.CompressedManifestStaticFilesStorage"
        )
    },
}
DEFAULT_AUTO_FIELD = "django.db.models.BigAutoField"

LOGIN_URL = "budget:login"
LOGIN_REDIRECT_URL = "labapps:portal"
LOGOUT_REDIRECT_URL = "budget:login"

SESSION_COOKIE_SECURE = not DEBUG
CSRF_COOKIE_SECURE = not DEBUG
SECURE_PROXY_SSL_HEADER = ("HTTP_X_FORWARDED_PROTO", "https")
SECURE_SSL_REDIRECT = not DEBUG
SECURE_HSTS_SECONDS = 0 if DEBUG else 31536000
SECURE_HSTS_INCLUDE_SUBDOMAINS = not DEBUG
SECURE_HSTS_PRELOAD = not DEBUG
SECURE_CONTENT_TYPE_NOSNIFF = True
X_FRAME_OPTIONS = "DENY"

PI_EMAIL = os.environ.get("PI_EMAIL", "kk4801@nyu.edu").strip().lower()
ALLOW_DEV_LOGIN = DEBUG and os.environ.get("ALLOW_DEV_LOGIN", "true").strip().lower() in {
    "1",
    "true",
    "yes",
}
DEV_AUTH_EMAIL = os.environ.get("DEV_AUTH_EMAIL", PI_EMAIL).strip().lower()
GOOGLE_OAUTH_CLIENT_ID = os.environ.get("GOOGLE_OAUTH_CLIENT_ID", "")
GOOGLE_OAUTH_CLIENT_SECRET = os.environ.get("GOOGLE_OAUTH_CLIENT_SECRET", "")
GOOGLE_OAUTH_REDIRECT_URI = os.environ.get("GOOGLE_OAUTH_REDIRECT_URI", "")
IAP_EXPECTED_AUDIENCE = os.environ.get("IAP_EXPECTED_AUDIENCE", "").strip()
MASTER_SPREADSHEET_ID = os.environ.get("MASTER_SPREADSHEET_ID", "")
REGISTRY_SPREADSHEET_ID = os.environ.get(
    "REGISTRY_SPREADSHEET_ID", ""
)
PROGRESS_SPREADSHEET_ID = os.environ.get(
    "PROGRESS_SPREADSHEET_ID", REGISTRY_SPREADSHEET_ID
).strip()
ENABLE_SHEET_WRITES = os.environ.get("ENABLE_SHEET_WRITES", "false").strip().lower() in {
    "1",
    "true",
    "yes",
}
SHEET_WRITE_ALLOWED_EMAILS = {
    email.strip().lower()
    for email in os.environ.get("SHEET_WRITE_ALLOWED_EMAILS", PI_EMAIL).split(",")
    if email.strip()
}
if not DEBUG and not BUILD_STATIC:
    oidc_configured = bool(GOOGLE_OAUTH_CLIENT_ID and GOOGLE_OAUTH_CLIENT_SECRET)
    if not IAP_EXPECTED_AUDIENCE and not oidc_configured:
        raise ImproperlyConfigured(
            "Configure IAP_EXPECTED_AUDIENCE or Google OIDC outside DEBUG mode."
        )
    if not INVOICE_BUCKET:
        raise ImproperlyConfigured("INVOICE_BUCKET is required outside DEBUG mode.")

LOGGING = {
    "version": 1,
    "disable_existing_loggers": False,
    "handlers": {"console": {"class": "logging.StreamHandler"}},
    "root": {"handlers": ["console"], "level": os.environ.get("LOG_LEVEL", "INFO")},
}
