from channels.generic.websocket import AsyncJsonWebsocketConsumer
from channels.db import database_sync_to_async
from knox.auth import TokenAuthentication
from django.contrib.auth import get_user_model
from accounts.models import Restaurant
from api.models import Order, Reservation, Payment, PaymentRefund
from urllib.parse import parse_qs
import logging

logger = logging.getLogger(__name__)

User = get_user_model()


class KnoxTokenAuthMixin:
    """Mixin to authenticate WebSocket connections using Knox token."""

    async def authenticate(self):
        # Used for debugging/logging rejections in connect()
        self._auth_error = None

        # Expect ?token=<knox_token> in query string
        query_string = self.scope.get("query_string", b"")
        token = self._extract_token_from_query_string(query_string)
        if not token:
            self._auth_error = "missing_token"
            return None

        try:
            user = await self._get_user_from_knox_token(token)
        except Exception as e:
            self._auth_error = "invalid_token"
            logger.warning(
                "WS token auth failed (token_key=%s len=%s err=%s)",
                token[:8],
                len(token),
                str(e)[:200],
            )
            return None

        if not user.is_active:
            self._auth_error = "inactive_user"
            return None
        self.scope["user"] = user
        return user

    @database_sync_to_async
    def _get_user_from_knox_token(self, token: str):
        # Mirrors the pattern from the reference project:
        # TokenAuthentication().authenticate_credentials(token.encode())
        user_auth_tuple = TokenAuthentication().authenticate_credentials(token.encode("utf-8"))
        return user_auth_tuple[0]

    def _extract_token_from_query_string(self, query_string: bytes):
        """Parse and normalize ?token=... from the raw ASGI query_string."""
        try:
            parsed = parse_qs((query_string or b"").decode("utf-8"))
        except Exception:
            return None

        token = (parsed.get("token") or [None])[0]
        if not token:
            return None

        token = str(token).strip().strip('"').strip("'")
        # Normalize token in case the client accidentally appends a trailing slash
        token = token.rstrip("/")
        # Be forgiving with common auth header formats being pasted into ?token=...
        # e.g. "Token <knox>" or "Bearer <knox>"
        if " " in token:
            token = token.split()[-1]
        return token or None


class RestaurantBaseConsumer(KnoxTokenAuthMixin, AsyncJsonWebsocketConsumer):
    """Base consumer for restaurant-scoped feeds using Knox auth."""

    async def connect(self):
        user = await self.authenticate()
        if not user:
            logger.warning(
                "WS auth failed (%s) path=%s client=%s",
                getattr(self, "_auth_error", None),
                self.scope.get("path"),
                self.scope.get("client"),
            )
            await self.close(code=4001)
            return

        is_admin = bool(user.is_staff or user.is_superuser or str(getattr(user, "role", "")).upper() == "ADMIN")

        # Only restaurant owners (or staff/superusers) are allowed
        restaurant = await self._get_restaurant_for_user(user)
        if not restaurant and not is_admin:
            logger.warning(
                "WS rejected: user has no restaurant and is not admin/staff (user_id=%s role=%s)",
                getattr(user, "id", None),
                getattr(user, "role", None),
            )
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
            return await self._get_restaurant_for_user_sync(user)
        except Exception:
            return None

    async def _get_group_name(self):
        raise NotImplementedError

    @database_sync_to_async
    def _get_restaurant_for_user_sync(self, user):
        return Restaurant.objects.filter(user=user).first()


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
