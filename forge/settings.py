from pathlib import Path
import os
from urllib.parse import parse_qs, unquote, urlparse

from sketches.pipeline.envload import read_dotenv

ROOT = Path(__file__).resolve().parent.parent
ENV = read_dotenv(ROOT / ".env")

# Detect Vercel / serverless runtime
_ON_VERCEL = bool(os.environ.get("VERCEL") or os.environ.get("VERCEL_ENV"))
_TMP = Path("/tmp") if _ON_VERCEL else ROOT


def _env_bool(name: str, default: bool) -> bool:
    value = ENV.get(name)
    if value is None:
        return default
    return value.strip().lower() in {"1", "true", "yes", "on"}


def _database_from_env() -> dict:
    database_url = (ENV.get("DATABASE_URL") or os.environ.get("DATABASE_URL") or "").strip()
    if database_url:
        parsed = urlparse(database_url)
        if parsed.scheme in {"postgres", "postgresql", "pgsql"}:
            options: dict[str, str] = {}
            query = parse_qs(parsed.query)
            if sslmode := query.get("sslmode", [None])[0]:
                options["sslmode"] = sslmode
            return {
                "ENGINE": "django.db.backends.postgresql",
                "NAME": unquote((parsed.path or "/forge").lstrip("/")) or "forge",
                "USER": unquote(parsed.username or ""),
                "PASSWORD": unquote(parsed.password or ""),
                "HOST": parsed.hostname or "localhost",
                "PORT": str(parsed.port or "5432"),
                "CONN_MAX_AGE": int(ENV.get("DB_CONN_MAX_AGE", "60")),
                "OPTIONS": options,
            }

    if ENV.get("POSTGRES_DB") or ENV.get("POSTGRES_HOST"):
        return {
            "ENGINE": "django.db.backends.postgresql",
            "NAME": ENV.get("POSTGRES_DB", "forge"),
            "USER": ENV.get("POSTGRES_USER", "postgres"),
            "PASSWORD": ENV.get("POSTGRES_PASSWORD", ""),
            "HOST": ENV.get("POSTGRES_HOST", "127.0.0.1"),
            "PORT": ENV.get("POSTGRES_PORT", "5432"),
            "CONN_MAX_AGE": int(ENV.get("DB_CONN_MAX_AGE", "60")),
            "OPTIONS": {"sslmode": ENV.get("POSTGRES_SSLMODE", "prefer")},
        }

    # On Vercel, /var/task is read-only — use /tmp for SQLite.
    db_path = ENV.get("DB_PATH") or ("/tmp/forge.db" if _ON_VERCEL else str(ROOT / "forge.db"))
    return {
        "ENGINE": "django.db.backends.sqlite3",
        "NAME": db_path,
    }

SECRET_KEY = ENV.get("SECRET_KEY") or os.environ.get("SECRET_KEY") or "dev-only-do-not-ship-this"
# Default OFF in production (Vercel sets VERCEL_ENV); default ON locally.
DEBUG = _env_bool("DEBUG", default=not _ON_VERCEL)
ALLOWED_HOSTS = ["*"]

# Build CSRF trusted origins: always include localhost, plus any Vercel domains.
_vercel_url = os.environ.get("VERCEL_URL") or ENV.get("VERCEL_URL") or ""
_vercel_project_url = os.environ.get("VERCEL_PROJECT_PRODUCTION_URL") or ""
CSRF_TRUSTED_ORIGINS = [
    "http://127.0.0.1:8765",
    "http://localhost:8765",
    "http://127.0.0.1:8000",
    "http://localhost:8000",
    "https://*.vercel.app",
]
if _vercel_url:
    CSRF_TRUSTED_ORIGINS.append(f"https://{_vercel_url}")
if _vercel_project_url:
    CSRF_TRUSTED_ORIGINS.append(f"https://{_vercel_project_url}")
# Allow override via env var (e.g. custom domain)
for _origin in (ENV.get("EXTRA_CSRF_ORIGINS") or "").split(","):
    if _origin.strip():
        CSRF_TRUSTED_ORIGINS.append(_origin.strip())

CSRF_COOKIE_SAMESITE = "Lax"
SESSION_COOKIE_SAMESITE = "Lax"
CSRF_COOKIE_SECURE = _env_bool("CSRF_COOKIE_SECURE", _ON_VERCEL)
SESSION_COOKIE_SECURE = _env_bool("SESSION_COOKIE_SECURE", _ON_VERCEL)

INSTALLED_APPS = [
    "django.contrib.admin",
    "django.contrib.auth",
    "django.contrib.contenttypes",
    "django.contrib.sessions",
    "django.contrib.messages",
    "django.contrib.staticfiles",
    "sketches.apps.SketchesConfig",
]

MIDDLEWARE = [
    "django.middleware.security.SecurityMiddleware",
    "whitenoise.middleware.WhiteNoiseMiddleware",
    "django.contrib.sessions.middleware.SessionMiddleware",
    "django.middleware.common.CommonMiddleware",
    "django.middleware.csrf.CsrfViewMiddleware",
    "django.contrib.auth.middleware.AuthenticationMiddleware",
    "django.contrib.messages.middleware.MessageMiddleware",
]

ROOT_URLCONF = "forge.urls"
WSGI_APPLICATION = "forge.wsgi.application"

TEMPLATES = [{
    "BACKEND": "django.template.backends.django.DjangoTemplates",
    "DIRS": [],
    "APP_DIRS": True,
    "OPTIONS": {"context_processors": [
        "django.template.context_processors.request",
        "django.contrib.auth.context_processors.auth",
        "django.contrib.messages.context_processors.messages",
    ]},
}]

DATABASES = {"default": _database_from_env()}

USE_TZ = True
TIME_ZONE = "UTC"
LANGUAGE_CODE = "en-us"
DEFAULT_AUTO_FIELD = "django.db.models.BigAutoField"

STATIC_URL = "static/"
STATIC_ROOT = ROOT / "staticfiles"  # collectstatic output; served by WhiteNoise
MEDIA_URL = "/renders/"
MEDIA_ROOT = _TMP / "renders"   # /tmp/renders on Vercel; ROOT/renders locally

STORAGES = {
    "default": {"BACKEND": "django.core.files.storage.FileSystemStorage"},
    "staticfiles": {
        "BACKEND": "whitenoise.storage.CompressedManifestStaticFilesStorage",
    },
}

# pipeline knobs
SCAD_BIN = ENV.get("SCAD_BIN") or None      # auto-detected if unset
GEMINI_KEY = ENV.get("GEMINI_KEY") or None  # if unset → offline heuristic
OPENAI_API_KEY = ENV.get("OPENAI_API_KEY") or ENV.get("OPENAI_KEY") or None
OPENAI_MODEL = ENV.get("OPENAI_MODEL", "gpt-5.5")
# Per-phase models. Defaults fall back to OPENAI_MODEL. Recommended:
#   PLAN model    → reasoning model (gpt-5.5) for briefs, decomposition, interface extraction
#   CODE model    → a fast, accurate coding model for SCAD generation + composition
# Examples to try in .env:
#   OPENAI_PLAN_MODEL=gpt-5.5
#   OPENAI_CODE_MODEL=gpt-5.5-codex
OPENAI_PLAN_MODEL = ENV.get("OPENAI_PLAN_MODEL") or OPENAI_MODEL
OPENAI_CODE_MODEL = ENV.get("OPENAI_CODE_MODEL") or OPENAI_MODEL
OPENAI_BASE_URL = ENV.get("OPENAI_BASE_URL", "https://api.openai.com/v1")
OPENAI_EMBED_MODEL = ENV.get("OPENAI_EMBED_MODEL", "text-embedding-3-small")
OPENAI_EMBED_DIM = int(ENV.get("OPENAI_EMBED_DIM", "1536"))
# Reasoning effort for gpt-5.x reasoning models: minimal | low | medium | high.
# "low" gets tokens flowing in seconds instead of minutes — much better UX.
OPENAI_REASONING_EFFORT = ENV.get("OPENAI_REASONING_EFFORT", "low")
PREFERRED_PROVIDER = ENV.get("PREFERRED_PROVIDER", "openai")
GENERATION_TIMEOUT = int(ENV.get("GENERATION_TIMEOUT", "600"))
RENDER_PX = int(ENV.get("RENDER_PX", "640"))
SCAD_MAX_CHARS = int(ENV.get("SCAD_MAX_CHARS", "24000"))
SCAD_RENDER_TIMEOUT = int(ENV.get("SCAD_RENDER_TIMEOUT", "300"))
BRIDGE_TEMPLATE_FIRST = ENV.get("BRIDGE_TEMPLATE_FIRST", "0") == "1"
STANDARDS_STORAGE_DIR = Path(ENV.get("STANDARDS_STORAGE_DIR") or str(_TMP / "standards_store"))
STANDARDS_CHUNK_SIZE = int(ENV.get("STANDARDS_CHUNK_SIZE", "1600"))
STANDARDS_CHUNK_OVERLAP = int(ENV.get("STANDARDS_CHUNK_OVERLAP", "200"))
