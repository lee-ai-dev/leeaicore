from channels.generic.websocket import AsyncJsonWebsocketConsumer
from knox.models import AuthToken
from django.contrib.auth import get_user_model
from accounts.models import Restaurant
from api.models import Order, Reservation, Payment, PaymentRefund
from urllib.parse import parse_qs

User = get_user_model()


class KnoxTokenAuthMixin:
    """Mixin to authenticate WebSocket connections using Knox token."""

    async def authenticate(self):
        # Expect ?token=<knox_token> in query string
        query_string = self.scope.get("query_string", b"").decode("utf-8")
        params = parse_qs(query_string)
        token = (params.get("token") or [None])[0]
        if not token:
            return None
        try:
            auth_token = AuthToken.objects.select_related("user").get(token_key=token[:8])
        except AuthToken.DoesNotExist:
            return None
        user = auth_token.user
        if not user.is_active:
            return None
        self.scope["user"] = user
        return user


class RestaurantBaseConsumer(KnoxTokenAuthMixin, AsyncJsonWebsocketConsumer):
    """Base consumer for restaurant-scoped feeds using Knox auth."""

    async def connect(self):
        user = await self.authenticate()
        if not user:
            await self.close(code=4001)
            return

        # Only restaurant owners (or staff/superusers) are allowed
        restaurant = await self._get_restaurant_for_user(user)
        if not restaurant and not (user.is_staff or user.is_superuser):
            await self.close(code=4003)
            return

        self.restaurant_id = restaurant.id if restaurant else None
        self.group_name = await self._get_group_name()

        await self.channel_layer.group_add(self.group_name, self.channel_name)
        await self.accept()

    async def disconnect(self, close_code):
        if hasattr(self, "group_name"):
            await self.channel_layer.group_discard(self.group_name, self.channel_name)

    async def _get_restaurant_for_user(self, user):
        try:
            return await self._database_sync_to_async(Restaurant.objects.filter(user=user).first)()
        except Exception:
            return None

    async def _get_group_name(self):
        raise NotImplementedError

    async def _database_sync_to_async(self, func, *args, **kwargs):
        from asgiref.sync import sync_to_async

        return await sync_to_async(func, thread_sensitive=True)(*args, **kwargs)


class RestaurantOrdersConsumer(RestaurantBaseConsumer):
    """Real-time feed of orders for a restaurant owner."""

    async def _get_group_name(self):
        return f"restaurant_orders_{self.restaurant_id}" if self.restaurant_id else "restaurant_orders_all"

    async def restaurant_order_event(self, event):
        # Event sent by signal layer
        await self.send_json(event.get("payload", {}))


class RestaurantReservationsConsumer(RestaurantBaseConsumer):
    """Real-time feed of reservations for a restaurant owner."""

    async def _get_group_name(self):
        return f"restaurant_reservations_{self.restaurant_id}" if self.restaurant_id else "restaurant_reservations_all"

    async def restaurant_reservation_event(self, event):
        await self.send_json(event.get("payload", {}))


class RestaurantPaymentsConsumer(RestaurantBaseConsumer):
    """Real-time feed of payments and refunds for a restaurant owner."""

    async def _get_group_name(self):
        return f"restaurant_payments_{self.restaurant_id}" if self.restaurant_id else "restaurant_payments_all"

    async def restaurant_payment_event(self, event):
        await self.send_json(event.get("payload", {}))
