"""
Django settings for Perspective Loom (ai_project).

Configured for secure defaults, environment-driven secrets, SQLite/PostgreSQL
support, and structured log redaction.
"""

from __future__ import annotations

import logging
import os
import secrets
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

BASE_DIR = Path(__file__).resolve().parent.parent


def _load_dotenv_if_present(env_path: Path) -> None:
    """Lightweight .env loader without requiring external dotenv packages."""
    if not env_path.exists():
        return
    for raw_line in env_path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        key = key.strip()
        value = value.strip().strip("'").strip('"')
        if key and key not in os.environ:
            os.environ[key] = value


_load_dotenv_if_present(BASE_DIR / ".env")


def _env_bool(name: str, default: bool = False) -> bool:
    val = os.getenv(name)
    if val is None:
        return default
    return val.strip().lower() in {"1", "true", "yes", "on"}


def _env_list(name: str, default: list[str]) -> list[str]:
    val = os.getenv(name)
    if not val:
        return default
    return [item.strip() for item in val.split(",") if item.strip()]


# Security-sensitive configuration moved to environment variables.
# Defaults to DEBUG=False for safety.
DEBUG: bool = _env_bool("DJANGO_DEBUG", default=False)

SECRET_KEY: str = os.getenv("DJANGO_SECRET_KEY") or (
    "dev-ephemeral-" + secrets.token_urlsafe(48)
)

ALLOWED_HOSTS: list[str] = _env_list(
    "DJANGO_ALLOWED_HOSTS", ["localhost", "127.0.0.1", "testserver"]
)

# Authentication & Data Retention settings
REQUIRE_AUTH: bool = _env_bool("REQUIRE_AUTH", default=False)
PERSPECTIVE_LOOM_API_KEY: str = os.getenv("PERSPECTIVE_LOOM_API_KEY", "")
DATA_RETENTION_DAYS: int = int(os.getenv("DATA_RETENTION_DAYS", "90"))

# Model Provider configuration
DEFAULT_MODEL_PROVIDER: str = os.getenv("DEFAULT_MODEL_PROVIDER", "fake")
DEFAULT_HOSTED_MODEL: str = os.getenv("DEFAULT_HOSTED_MODEL", "gpt-4o-mini")
DEFAULT_OLLAMA_MODEL: str = os.getenv("DEFAULT_OLLAMA_MODEL", "llama3.2")
OPENAI_BASE_URL: str = os.getenv(
    "OPENAI_BASE_URL", "https://models.inference.ai.azure.com"
)
OLLAMA_HOST: str = os.getenv("OLLAMA_HOST", "http://localhost:11434")
PROVIDER_TIMEOUT_SECONDS: float = float(os.getenv("PROVIDER_TIMEOUT_SECONDS", "30.0"))
PROVIDER_MAX_RETRIES: int = int(os.getenv("PROVIDER_MAX_RETRIES", "2"))


INSTALLED_APPS = [
    "django.contrib.admin",
    "django.contrib.auth",
    "django.contrib.contenttypes",
    "django.contrib.sessions",
    "django.contrib.messages",
    "django.contrib.staticfiles",
    "ai_app",
]

# Include corsheaders only if installed in the active environment
try:
    import corsheaders  # noqa: F401

    INSTALLED_APPS.append("corsheaders")
    _HAS_CORSHEADERS = True
except ImportError:
    _HAS_CORSHEADERS = False

MIDDLEWARE = [
    *(["corsheaders.middleware.CorsMiddleware"] if _HAS_CORSHEADERS else []),
    "django.middleware.security.SecurityMiddleware",
    "django.contrib.sessions.middleware.SessionMiddleware",
    "django.middleware.common.CommonMiddleware",
    "django.middleware.csrf.CsrfViewMiddleware",
    "django.contrib.auth.middleware.AuthenticationMiddleware",
    "django.contrib.messages.middleware.MessageMiddleware",
    "django.middleware.clickjacking.XFrameOptionsMiddleware",
]

ROOT_URLCONF = "ai_project.urls"

TEMPLATES = [
    {
        "BACKEND": "django.template.backends.django.DjangoTemplates",
        "DIRS": [],
        "APP_DIRS": True,
        "OPTIONS": {
            "context_processors": [
                "django.template.context_processors.debug",
                "django.template.context_processors.request",
                "django.contrib.auth.context_processors.auth",
                "django.contrib.messages.context_processors.messages",
            ],
        },
    },
]

WSGI_APPLICATION = "ai_project.wsgi.application"
ASGI_APPLICATION = "ai_project.asgi.application"


def _parse_database_url(db_url: str) -> dict[str, Any]:
    """Parse DATABASE_URL supporting PostgreSQL and SQLite without third-party dependencies."""
    if db_url.startswith("sqlite:///"):
        db_path = db_url.replace("sqlite:///", "", 1)
        return {
            "ENGINE": "django.db.backends.sqlite3",
            "NAME": db_path or str(BASE_DIR / "db.sqlite3"),
        }
    parsed = urlparse(db_url)
    if parsed.scheme in {"postgres", "postgresql", "pgsql"}:
        return {
            "ENGINE": "django.db.backends.postgresql",
            "NAME": parsed.path.lstrip("/"),
            "USER": parsed.username or "",
            "PASSWORD": parsed.password or "",
            "HOST": parsed.hostname or "localhost",
            "PORT": str(parsed.port or 5432),
            "CONN_MAX_AGE": int(os.getenv("DB_CONN_MAX_AGE", "60")),
        }
    raise ValueError(f"Unsupported DATABASE_URL scheme: {parsed.scheme}")


_database_url = os.getenv("DATABASE_URL", "").strip()
if _database_url:
    DATABASES = {"default": _parse_database_url(_database_url)}
else:
    DATABASES = {
        "default": {
            "ENGINE": "django.db.backends.sqlite3",
            "NAME": BASE_DIR / "db.sqlite3",
        }
    }


AUTH_PASSWORD_VALIDATORS = [
    {
        "NAME": "django.contrib.auth.password_validation.UserAttributeSimilarityValidator",
    },
    {
        "NAME": "django.contrib.auth.password_validation.MinimumLengthValidator",
    },
    {
        "NAME": "django.contrib.auth.password_validation.CommonPasswordValidator",
    },
    {
        "NAME": "django.contrib.auth.password_validation.NumericPasswordValidator",
    },
]

LANGUAGE_CODE = "en-us"
TIME_ZONE = "UTC"
USE_I18N = True
USE_TZ = True

STATIC_URL = "static/"
DEFAULT_AUTO_FIELD = "django.db.models.BigAutoField"

CORS_ALLOWED_ORIGINS = _env_list(
    "CORS_ALLOWED_ORIGINS",
    [
        "http://localhost:3000",
        "http://localhost:5173",
    ],
)
CORS_ALLOW_CREDENTIALS = False

# Security headers when running with DEBUG=False
if not DEBUG:
    SECURE_CONTENT_TYPE_NOSNIFF = True
    X_FRAME_OPTIONS = "DENY"
    SESSION_COOKIE_HTTPONLY = True
    CSRF_COOKIE_HTTPONLY = True


class SensitiveDataRedactionFilter(logging.Filter):
    """Prevents API keys, tokens, and raw user prompts from leaking into logs."""

    SENSITIVE_KEYS = ("GITHUB_TOKEN", "OPENAI_API_KEY", "PERSPECTIVE_LOOM_API_KEY")

    def filter(self, record: logging.LogRecord) -> bool:
        msg = record.getMessage()
        for env_key in self.SENSITIVE_KEYS:
            secret_val = os.getenv(env_key)
            if secret_val and len(secret_val) > 4 and secret_val in msg:
                msg = msg.replace(secret_val, "[REDACTED_SECRET]")
        record.msg = msg
        record.args = ()
        return True


LOGGING = {
    "version": 1,
    "disable_existing_loggers": False,
    "filters": {
        "redact_secrets": {
            "()": "ai_project.settings.SensitiveDataRedactionFilter",
        },
    },
    "formatters": {
        "structured": {
            "format": "{asctime} [{levelname}] {name} ({module}:{lineno:d}): {message}",
            "style": "{",
        },
    },
    "handlers": {
        "console": {
            "class": "logging.StreamHandler",
            "formatter": "structured",
            "filters": ["redact_secrets"],
        },
    },
    "loggers": {
        "ai_app": {
            "handlers": ["console"],
            "level": "DEBUG" if DEBUG else "INFO",
            "propagate": False,
        },
    },
}
