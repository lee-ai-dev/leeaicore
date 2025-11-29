from pathlib import Path
import os
from dotenv import load_dotenv

load_dotenv()

# Build paths inside the project like this: BASE_DIR / 'subdir'.
BASE_DIR = Path(__file__).resolve().parent.parent

# SECURITY WARNING: keep the secret key used in production secret!
SECRET_KEY = 'django-insecure--wr_(881a=5d%b1-3=_t2592v7!iz%b8p%93!kf$1s4)x)-^q-'

# SECURITY WARNING: don't run with debug turned on in production!
DEBUG = True

ALLOWED_HOSTS = ["*"]


# Application definition

INSTALLED_APPS = [
    'django.contrib.admin',
    'django.contrib.auth',
    'django.contrib.contenttypes',
    'django.contrib.sessions',
    'django.contrib.messages',
    'django.contrib.staticfiles',

    # internal apps
    'accounts.apps.AccountsConfig',
    'api.apps.ApiConfig',
    'agentic.apps.AgenticConfig',

    # Third-party apps
    'corsheaders',
    'rest_framework',
    'knox',
    'drf_spectacular',
    'django_filters',

    # root app 
    # to is so that management commands work from root app
    'leeaicore',

]

MIDDLEWARE = [
    'django.middleware.security.SecurityMiddleware',
    'django.contrib.sessions.middleware.SessionMiddleware',
    'corsheaders.middleware.CorsMiddleware',
    'django.middleware.common.CommonMiddleware',
    'django.middleware.csrf.CsrfViewMiddleware',
    'django.contrib.auth.middleware.AuthenticationMiddleware',
    'django.contrib.messages.middleware.MessageMiddleware',
    'django.middleware.clickjacking.XFrameOptionsMiddleware',
]

ROOT_URLCONF = 'leeaicore.urls'

TEMPLATES = [
    {
        'BACKEND': 'django.template.backends.django.DjangoTemplates',
        'DIRS': [],
        'APP_DIRS': True,
        'OPTIONS': {
            'context_processors': [
                'django.template.context_processors.request',
                'django.contrib.auth.context_processors.auth',
                'django.contrib.messages.context_processors.messages',
            ],
        },
    },
]

WSGI_APPLICATION = 'leeaicore.wsgi.application'


# Database
# https://docs.djangoproject.com/en/5.2/ref/settings/#databases

DATABASES = {
    'default': {
        'ENGINE': 'django.db.backends.sqlite3',
        'NAME': BASE_DIR / 'db.sqlite3',
    }
}


# Password validation
# https://docs.djangoproject.com/en/5.2/ref/settings/#auth-password-validators

AUTH_PASSWORD_VALIDATORS = [
    {
        'NAME': 'django.contrib.auth.password_validation.UserAttributeSimilarityValidator',
    },
    {
        'NAME': 'django.contrib.auth.password_validation.MinimumLengthValidator',
    },
    {
        'NAME': 'django.contrib.auth.password_validation.CommonPasswordValidator',
    },
    {
        'NAME': 'django.contrib.auth.password_validation.NumericPasswordValidator',
    },
]

# custom user model
AUTH_USER_MODEL = 'accounts.User'


# Internationalization
# https://docs.djangoproject.com/en/5.2/topics/i18n/

LANGUAGE_CODE = 'en-us'

TIME_ZONE = 'UTC'

USE_I18N = True

USE_TZ = True


# Static files (CSS, JavaScript, Images)
# https://docs.djangoproject.com/en/5.2/howto/static-files/

STATIC_URL = '/static/'
STATIC_ROOT = BASE_DIR / 'staticfiles/'

STATICFILES_DIRS = [
    BASE_DIR / "static",
]

MEDIA_URL = '/assets/'
MEDIA_ROOT = BASE_DIR / "assets"

# Django REST Framework Configuration
REST_FRAMEWORK = {
    'DEFAULT_AUTHENTICATION_CLASSES': [
        'knox.auth.TokenAuthentication',
    ],
    'DEFAULT_SCHEMA_CLASS': 'drf_spectacular.openapi.AutoSchema',
    'DEFAULT_FILTER_BACKENDS': [
        'django_filters.rest_framework.DjangoFilterBackend',
        'rest_framework.filters.SearchFilter',
        'rest_framework.filters.OrderingFilter',
    ],
    # Pagination
    'DEFAULT_PAGINATION_CLASS': 'rest_framework.pagination.PageNumberPagination',
    'PAGE_SIZE': int(os.getenv('API_PAGE_SIZE', 20)),
    # Throttling
    'DEFAULT_THROTTLE_CLASSES': [
        'leeaicore.sysutils.throttling.RoleBasedScopedRateThrottle',
    ],
    'DEFAULT_THROTTLE_RATES': {
        # Fallback scopes
        'chatbot': os.getenv('THROTTLE_CHATBOT', '60/min'),
        'orders': os.getenv('THROTTLE_ORDERS', '30/min'),
        'restaurant': os.getenv('THROTTLE_RESTAURANT', '60/min'),
        # Role-scoped overrides
        'anonymous:orders': os.getenv('THROTTLE_ANON_ORDERS', '10/min'),
        'user:orders': os.getenv('THROTTLE_USER_ORDERS', '30/min'),
        'restaurant:orders': os.getenv('THROTTLE_RESTAURANT_ORDERS', '90/min'),
        'admin:orders': os.getenv('THROTTLE_ADMIN_ORDERS', '120/min'),

        'anonymous:chatbot': os.getenv('THROTTLE_ANON_CHATBOT', '30/min'),
        'user:chatbot': os.getenv('THROTTLE_USER_CHATBOT', '60/min'),
        'restaurant:chatbot': os.getenv('THROTTLE_RESTAURANT_CHATBOT', '90/min'),
        'admin:chatbot': os.getenv('THROTTLE_ADMIN_CHATBOT', '120/min'),

        'anonymous:restaurant': os.getenv('THROTTLE_ANON_RESTAURANT', '10/min'),
        'user:restaurant': os.getenv('THROTTLE_USER_RESTAURANT', '20/min'),
        'restaurant:restaurant': os.getenv('THROTTLE_RESTAURANT_RESTAURANT', '90/min'),
        'admin:restaurant': os.getenv('THROTTLE_ADMIN_RESTAURANT', '120/min'),
    },
}
# knox - make token non-expiry
REST_KNOX = {
    'TOKEN_TTL': None,
}

# django cors headers settings
CORS_ALLOW_ALL_ORIGINS = True
# Default primary key field type
# https://docs.djangoproject.com/en/5.2/ref/settings/#default-auto-field

DEFAULT_AUTO_FIELD = 'django.db.models.BigAutoField'

# email settings
EMAIL_BACKEND = 'django.core.mail.backends.smtp.EmailBackend'
EMAIL_HOST = 'smtp.gmail.com'
EMAIL_PORT = 587
EMAIL_HOST_USER = ''
EMAIL_HOST_PASSWORD = ''
EMAIL_USE_TLS = True
EMAIL_USE_SSL = False
DEFAULT_FROM_EMAIL = os.getenv('DEFAULT_FROM_MAIL')

# SMS SETTINGS
SENDER_ID = os.getenv('SMS_SENDER_ID') # 11 characters max
ARKESEL_API_KEY = os.getenv('ARKESEL_SMS_API_KEY')

# DRF Spectacular settings
SPECTACULAR_SETTINGS = {
    'TITLE': 'LEE AI API',
    'DESCRIPTION': 'LEE AI CORE API',
    'VERSION': '1.0.0',
    'SERVE_INCLUDE_SCHEMA': False,
}

# OpenAI settings (optional; features will gracefully degrade without a key)
OPENAI_API_KEY = os.getenv('OPENAI_API_KEY', '')
OPENAI_MODEL = os.getenv('OPENAI_MODEL', 'gpt-4o-mini')

# Payment provider selection (mock by default)
PAYMENT_PROVIDER = os.getenv('PAYMENT_PROVIDER', 'MOCK')
PAYSTACK_SECRET_KEY = os.getenv('PAYSTACK_SECRET_KEY', '')
PAYSTACK_PUBLIC_KEY = os.getenv('PAYSTACK_PUBLIC_KEY', '')
PAYSTACK_BASE_URL = os.getenv('PAYSTACK_BASE_URL', 'https://api.paystack.co')