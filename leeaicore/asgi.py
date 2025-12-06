"""
ASGI config for leeaicore project.

It exposes the ASGI callable as a module-level variable named ``application``.

For more information on this file, see
https://docs.djangoproject.com/en/5.2/howto/deployment/asgi/
"""

import os

from django.core.asgi import get_asgi_application
from channels.routing import ProtocolTypeRouter, URLRouter
from channels.auth import AuthMiddlewareStack
from django.urls import path

os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'leeaicore.settings')

django_asgi_app = get_asgi_application()


def get_websocket_urlpatterns():
	# Import consumers lazily so Django settings are fully configured
	from api import consumers as api_consumers
	return [
		path('ws/restaurant/orders/', api_consumers.RestaurantOrdersConsumer.as_asgi()),
		path('ws/restaurant/reservations/', api_consumers.RestaurantReservationsConsumer.as_asgi()),
		path('ws/restaurant/payments/', api_consumers.RestaurantPaymentsConsumer.as_asgi()),
	]


application = ProtocolTypeRouter({
	"http": django_asgi_app,
	"websocket": AuthMiddlewareStack(
		URLRouter(get_websocket_urlpatterns())
	),
})
