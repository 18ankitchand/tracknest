import os
import json
import logging
from pathlib import Path
import dj_database_url
BASE_DIR=Path(__file__).resolve().parent.parent
DEBUG=os.environ.get('DJANGO_DEBUG','1')=='1'
SECRET_KEY=os.environ.get('DJANGO_SECRET_KEY')
if not SECRET_KEY:
    if not DEBUG:
        raise RuntimeError('DJANGO_SECRET_KEY must be set in production')
    SECRET_KEY='unsafe-dev-key-not-for-production'
ALLOWED_HOSTS=[x.strip() for x in os.environ.get('DJANGO_ALLOWED_HOSTS','127.0.0.1,localhost').split(',') if x.strip()]
CSRF_TRUSTED_ORIGINS=[x.strip() for x in os.environ.get('DJANGO_CSRF_TRUSTED_ORIGINS','').split(',') if x.strip()]
INSTALLED_APPS=['django.contrib.admin','django.contrib.auth','django.contrib.contenttypes','django.contrib.sessions','django.contrib.messages','django.contrib.staticfiles','accounts']
MIDDLEWARE=['django.middleware.security.SecurityMiddleware','whitenoise.middleware.WhiteNoiseMiddleware','django.contrib.sessions.middleware.SessionMiddleware','django.middleware.common.CommonMiddleware','django.middleware.csrf.CsrfViewMiddleware','django.contrib.auth.middleware.AuthenticationMiddleware','django.contrib.messages.middleware.MessageMiddleware','django.middleware.clickjacking.XFrameOptionsMiddleware']
ROOT_URLCONF='config.urls'
TEMPLATES=[{'BACKEND':'django.template.backends.django.DjangoTemplates','DIRS':[BASE_DIR/'templates'],'APP_DIRS':True,'OPTIONS':{'context_processors':['django.template.context_processors.debug','django.template.context_processors.request','django.contrib.auth.context_processors.auth','django.contrib.messages.context_processors.messages']}}]
WSGI_APPLICATION='config.wsgi.application'
# PostgreSQL on Render; local SQLite only for development.
DATABASE_URL=os.environ.get('DATABASE_URL')
if not DEBUG and not DATABASE_URL:
    raise RuntimeError('DATABASE_URL must be set in production')
DATABASES={'default': dj_database_url.parse(DATABASE_URL, conn_max_age=600, conn_health_checks=True) if DATABASE_URL else {'ENGINE':'django.db.backends.sqlite3','NAME':BASE_DIR/'db.sqlite3'}}
AUTH_PASSWORD_VALIDATORS=[{'NAME':'django.contrib.auth.password_validation.UserAttributeSimilarityValidator'},{'NAME':'django.contrib.auth.password_validation.MinimumLengthValidator'},{'NAME':'django.contrib.auth.password_validation.CommonPasswordValidator'},{'NAME':'django.contrib.auth.password_validation.NumericPasswordValidator'}]
LANGUAGE_CODE='en-us'
TIME_ZONE='Asia/Kathmandu'
USE_TZ=True
STATIC_URL='static/'
STATICFILES_DIRS=[BASE_DIR/'static']
STATIC_ROOT=BASE_DIR/'staticfiles'
STORAGES={'staticfiles': {'BACKEND': 'whitenoise.storage.CompressedManifestStaticFilesStorage'}}
SECURE_PROXY_SSL_HEADER=('HTTP_X_FORWARDED_PROTO','https')
SESSION_COOKIE_SECURE=not DEBUG
CSRF_COOKIE_SECURE=not DEBUG
SECURE_SSL_REDIRECT=not DEBUG
SECURE_CONTENT_TYPE_NOSNIFF=True
DEFAULT_AUTO_FIELD='django.db.models.BigAutoField'
SESSION_COOKIE_HTTPONLY=True
CSRF_COOKIE_SAMESITE='Lax'
SESSION_COOKIE_SAMESITE='Lax'

# On macOS, the optional local sender configuration lives outside the Git repository.
# ~/.tracknest/email.json must be readable only by the account owner (chmod 600).
# Environment variables take precedence (use these when deploying to a host).
_local_mail = {}
_local_mail_file = Path.home() / ".tracknest" / "email.json"
if _local_mail_file.is_file():
    try:
        if os.name == "posix" and _local_mail_file.stat().st_mode & 0o077:
            raise ValueError("Email settings file must be private (chmod 600).")
        _local_mail = json.loads(_local_mail_file.read_text(encoding="utf-8"))
        if not isinstance(_local_mail, dict):
            raise ValueError("Email settings must be a JSON object.")
    except (OSError, ValueError, json.JSONDecodeError) as exc:
        logging.getLogger(__name__).warning("Local email configuration unavailable: %s", exc)
        _local_mail = {}

_mail_user = os.environ.get("DJANGO_EMAIL_HOST_USER", _local_mail.get("email", ""))
_mail_password = os.environ.get("DJANGO_EMAIL_HOST_PASSWORD", _local_mail.get("app_password", ""))
_use_real_mail = bool(_mail_user and _mail_password)
EMAIL_BACKEND = os.environ.get(
    "DJANGO_EMAIL_BACKEND",
    "django.core.mail.backends.smtp.EmailBackend" if _use_real_mail
    else "django.core.mail.backends.console.EmailBackend",
)
EMAIL_HOST = os.environ.get("DJANGO_EMAIL_HOST", "smtp.gmail.com" if _use_real_mail else "")
EMAIL_PORT = int(os.environ.get("DJANGO_EMAIL_PORT", "587"))
EMAIL_USE_TLS = os.environ.get("DJANGO_EMAIL_USE_TLS", "1") == "1"
EMAIL_HOST_USER = _mail_user
EMAIL_HOST_PASSWORD = _mail_password
EMAIL_TIMEOUT = 15
DEFAULT_FROM_EMAIL = os.environ.get("DJANGO_DEFAULT_FROM_EMAIL", _mail_user or "TrackNest <no-reply@example.com>")

# eSewa ePay V2 (sandbox only). Never enable live payments with demo credentials.
# Store test credentials in private ~/.tracknest/esewa.json or environment variables.
_esewa_local = {}
_esewa_file = Path.home() / ".tracknest" / "esewa.json"
if _esewa_file.is_file():
    try:
        if os.name == "posix" and _esewa_file.stat().st_mode & 0o077:
            raise ValueError("eSewa config permissions must be 600")
        _esewa_local = json.loads(_esewa_file.read_text(encoding="utf-8"))
        if not isinstance(_esewa_local, dict):
            raise ValueError("Invalid eSewa config format")
    except (OSError, ValueError):
        logging.getLogger(__name__).warning("eSewa sandbox configuration unavailable.")
        _esewa_local = {}
# eSewa explicitly publishes these shared UAT credentials for developers.
# They are NOT live merchant credentials. The public key is usable in DEBUG only.
# Source: https://developer.esewa.com.np/pages/Test-credentials
_ESEWA_PUBLIC_UAT_CODE = "EPAYTEST"
_ESEWA_PUBLIC_UAT_KEY = "8gBm/:&EnhH.1/q"
ESEWA_SANDBOX_ENABLED = os.environ.get(
    "TRACKNEST_ESEWA_SANDBOX", str(_esewa_local.get("enabled", "true" if DEBUG else "false"))
).lower() in ("1", "true")
ESEWA_PRODUCT_CODE = os.environ.get(
    "TRACKNEST_ESEWA_PRODUCT_CODE", _esewa_local.get("product_code", _ESEWA_PUBLIC_UAT_CODE)
)
ESEWA_SECRET_KEY = os.environ.get(
    "TRACKNEST_ESEWA_SECRET_KEY", _esewa_local.get("secret_key", _ESEWA_PUBLIC_UAT_KEY if DEBUG else "")
)
# The sandbox checkout is intentionally disabled in any production deployment,
# even if an environment variable accidentally enables UAT credentials.
ESEWA_SANDBOX_READY = bool(
    DEBUG and ESEWA_SANDBOX_ENABLED
    and ESEWA_PRODUCT_CODE == _ESEWA_PUBLIC_UAT_CODE and ESEWA_SECRET_KEY
)
