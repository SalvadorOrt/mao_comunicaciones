"""
Django settings for mao_comunicaciones project.
"""

from pathlib import Path

import environ


# =========================================================
# RUTAS BASE
# =========================================================

BASE_DIR = Path(__file__).resolve().parent.parent


# =========================================================
# VARIABLES DE ENTORNO
# =========================================================

env = environ.Env()

environ.Env.read_env(BASE_DIR / ".env")

DJANGO_ENV = env(
    "DJANGO_ENV",
    default="local",
).lower()


# =========================================================
# SEGURIDAD / DJANGO
# =========================================================

SECRET_KEY = env(
    "DJANGO_SECRET_KEY",
    default="django-insecure-local-only-change-me",
)

DEBUG = env.bool(
    "DJANGO_DEBUG",
    default=False,
)

ALLOWED_HOSTS = env.list(
    "DJANGO_ALLOWED_HOSTS",
    default=[
        "localhost",
        "127.0.0.1",
    ],
)


# =========================================================
# APLICACIONES
# =========================================================

INSTALLED_APPS = [
    # Django
    "django.contrib.admin",
    "django.contrib.auth",
    "django.contrib.contenttypes",
    "django.contrib.sessions",
    "django.contrib.messages",
    "django.contrib.staticfiles",

    # MAO Comunicaciones
    "core",
    "organizacion",
    "comunicaciones",
    "integraciones",
]


# =========================================================
# MIDDLEWARE
# =========================================================

MIDDLEWARE = [
    "django.middleware.security.SecurityMiddleware",
    "django.contrib.sessions.middleware.SessionMiddleware",
    "django.middleware.common.CommonMiddleware",
    "django.middleware.csrf.CsrfViewMiddleware",
    "django.contrib.auth.middleware.AuthenticationMiddleware",
    "django.contrib.messages.middleware.MessageMiddleware",
    "django.middleware.clickjacking.XFrameOptionsMiddleware",
]


# =========================================================
# URLS / WSGI
# =========================================================

ROOT_URLCONF = "mao_comunicaciones.urls"

WSGI_APPLICATION = "mao_comunicaciones.wsgi.application"


# =========================================================
# TEMPLATES
# =========================================================

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


# =========================================================
# BASE DE DATOS
# =========================================================
#
# LOCAL:
#   SQLite
#
# PRODUCCIÓN:
#   PostgreSQL
#
# En producción:
# DJANGO_ENV=production
# =========================================================

if DJANGO_ENV == "production":

    DATABASES = {
        "default": {
            "ENGINE": "django.db.backends.postgresql",
            "NAME": env("DB_NAME"),
            "USER": env("DB_USER"),
            "PASSWORD": env("DB_PASSWORD"),
            "HOST": env(
                "DB_HOST",
                default="127.0.0.1",
            ),
            "PORT": env(
                "DB_PORT",
                default="5432",
            ),
            "CONN_MAX_AGE": 60,
        }
    }

else:

    DATABASES = {
        "default": {
            "ENGINE": "django.db.backends.sqlite3",
            "NAME": BASE_DIR / "db.sqlite3",
        }
    }


# =========================================================
# VALIDACIÓN DE CONTRASEÑAS
# =========================================================

AUTH_PASSWORD_VALIDATORS = [
    {
        "NAME": (
            "django.contrib.auth.password_validation."
            "UserAttributeSimilarityValidator"
        ),
    },
    {
        "NAME": (
            "django.contrib.auth.password_validation."
            "MinimumLengthValidator"
        ),
    },
    {
        "NAME": (
            "django.contrib.auth.password_validation."
            "CommonPasswordValidator"
        ),
    },
    {
        "NAME": (
            "django.contrib.auth.password_validation."
            "NumericPasswordValidator"
        ),
    },
]


# =========================================================
# IDIOMA / ZONA HORARIA
# =========================================================

LANGUAGE_CODE = "es"

TIME_ZONE = "America/Guayaquil"

USE_I18N = True

USE_TZ = True


# =========================================================
# ARCHIVOS ESTÁTICOS
# =========================================================

STATIC_URL = "/static/"

STATIC_ROOT = BASE_DIR / "staticfiles"


# =========================================================
# MULTIMEDIA
# =========================================================

MEDIA_URL = "/media/"

MEDIA_ROOT = BASE_DIR / "media"


# =========================================================
# EMAIL
# =========================================================
#
# Por el momento solamente consola.
# Luego podemos configurar Zoho.
# =========================================================

EMAIL_BACKEND = "django.core.mail.backends.console.EmailBackend"


# =========================================================
# META / WHATSAPP CLOUD API
# =========================================================

META_ACCESS_TOKEN = env(
    "META_ACCESS_TOKEN",
    default="",
)

META_API_VERSION = env(
    "META_API_VERSION",
    default="v20.0",
)

META_APP_SECRET = env(
    "META_APP_SECRET",
    default="",
)

META_VERIFY_TOKEN = env(
    "META_VERIFY_TOKEN",
    default="",
)


# =========================================================
# API INTERNA DE MAO COMUNICACIONES
# =========================================================
#
# Será utilizada posteriormente por:
#
# - ERP
# - MAO Asistente
# - MAO Citas
#
# para solicitar envíos a Comunicaciones.
# =========================================================

MAO_COMUNICACIONES_SERVICE_TOKEN = env(
    "MAO_COMUNICACIONES_SERVICE_TOKEN",
    default="",
)


# =========================================================
# CONFIGURACIÓN HTTPS / NGINX
# =========================================================
#
# Nginx termina HTTPS y comunica a Gunicorn internamente.
# Django debe reconocer X-Forwarded-Proto.
# =========================================================

SECURE_PROXY_SSL_HEADER = (
    "HTTP_X_FORWARDED_PROTO",
    "https",
)


# =========================================================
# COOKIES SEGURAS
# =========================================================

if DJANGO_ENV == "production":
    SESSION_COOKIE_SECURE = True
    CSRF_COOKIE_SECURE = True
else:
    SESSION_COOKIE_SECURE = False
    CSRF_COOKIE_SECURE = False


# =========================================================
# DEFAULT PRIMARY KEY
# =========================================================

DEFAULT_AUTO_FIELD = "django.db.models.BigAutoField"