from django.db import transaction
from django.db.models import Q
from drf_spectacular.utils import extend_schema, OpenApiParameter
from drf_spectacular.types import OpenApiTypes
from rest_framework import permissions, status
from rest_framework.response import Response
from rest_framework.views import APIView
from rest_framework.pagination import PageNumberPagination
from django.conf import settings
from decimal import Decimal

from accounts.models import Restaurant
from agentic.services import IntentEngine
from api.models import Complaint, Dish, Order, Payment, Reservation, Table
from api.serializers import (
	ComplaintSerializer,
	DishSerializer,
	DishCreateUpdateSerializer,
	MenuQuerySerializer,
	OrderSerializer,
	PaymentConfirmSerializer,
	PaymentIntentSerializer,
	PaymentSerializer,
	PlaceOrderSerializer,
	ReservationSerializer,
	TableSerializer,
	TableCreateUpdateSerializer,
	OrderStatusUpdateSerializer,
	ReservationStatusUpdateSerializer,
)
from leeaicore.sysutils.constants import ComplaintStatus, OrderStatus, PaymentStatus
from api.services import PaystackClient


class MenuListAPI(APIView):
	permission_classes = (permissions.AllowAny,)
	throttle_scope = 'restaurant'

	@extend_schema(
		parameters=[
			OpenApiParameter(name='restaurant_rid', type=OpenApiTypes.STR, location=OpenApiParameter.QUERY, required=False),
			OpenApiParameter(name='q', type=OpenApiTypes.STR, location=OpenApiParameter.QUERY, required=False),
		],
		responses={200: DishSerializer(many=True)},
		operation_id='retrieve_menu',
		description='Retrieve the menu. Filter by restaurant_rid or search by name/description.'
	)
	def get(self, request):
		ser = MenuQuerySerializer(data=request.query_params)
		ser.is_valid(raise_exception=True)
		rid = ser.validated_data.get("restaurant_rid")
		q = ser.validated_data.get("q")

		qs = Dish.objects.filter(in_stock=True)
		if rid:
			if not Restaurant.objects.filter(rid=rid).exists():
				return Response({"message": "Restaurant not found"}, status=404)
			qs = qs.filter(restaurant__rid=rid)
		if q:
			qs = qs.filter(Q(name__icontains=q) | Q(description__icontains=q))

		qs = qs.order_by("name")
		return Response(DishSerializer(qs, many=True).data)


class PlaceOrderAPI(APIView):
	permission_classes = (permissions.IsAuthenticated,)
	throttle_scope = 'orders'

	@extend_schema(request=PlaceOrderSerializer, responses={200: OrderSerializer}, operation_id='place_order')
	def post(self, request):
		ser = PlaceOrderSerializer(data=request.data, context={"request": request})
		ser.is_valid(raise_exception=True)
		order = ser.save()
		return Response(OrderSerializer(order).data, status=status.HTTP_200_OK)


class OrderStatusAPI(APIView):
	permission_classes = (permissions.IsAuthenticated,)
	throttle_scope = 'orders'

	@extend_schema(
		parameters=[OpenApiParameter(name='ord_id', type=OpenApiTypes.STR, location=OpenApiParameter.PATH, required=True)],
		responses={200: OrderSerializer},
		operation_id='check_order_status'
	)
	def get(self, request, ord_id: str):
		order = Order.objects.filter(ord_id=ord_id).first()
		if not order:
			return Response({"message": "Order not found"}, status=404)
		if not (order.user_id == request.user.id or request.user.is_staff or request.user.is_superuser):
			return Response({"message": "Not authorized"}, status=403)
		return Response(OrderSerializer(order).data)


class ReservationAPI(APIView):
	permission_classes = (permissions.IsAuthenticated,)
	throttle_scope = 'orders'

	@extend_schema(responses={200: ReservationSerializer(many=True)}, operation_id='list_reservations')
	def get(self, request):
		qs = Reservation.objects.filter(user=request.user).order_by("-created_at")
		paginator = PageNumberPagination()
		page = paginator.paginate_queryset(qs, request)
		data = ReservationSerializer(page or qs, many=True).data
		if page is not None:
			return paginator.get_paginated_response(data)
		return Response(data)

	@extend_schema(request=ReservationSerializer, responses={200: ReservationSerializer}, operation_id='create_reservation')
	@transaction.atomic
	def post(self, request):
		ser = ReservationSerializer(data=request.data)
		ser.is_valid(raise_exception=True)

		table = ser.validated_data["table"]
		restaurant = ser.validated_data["restaurant"]
		if not table.available:
			return Response({"message": "Table not available"}, status=400)

		reservation = Reservation.objects.create(
			table=table,
			restaurant=restaurant,
			user=request.user,
		)
		# Mark table not available
		Table.objects.filter(pk=table.pk, available=True).update(available=False)
		reservation.refresh_from_db()
		return Response(ReservationSerializer(reservation).data)


class ComplaintAPI(APIView):
	permission_classes = (permissions.IsAuthenticated,)
	throttle_scope = 'orders'

	@extend_schema(request=ComplaintSerializer, responses={200: ComplaintSerializer}, operation_id='submit_complaint')
	def post(self, request):
		data = {**request.data}
		ser = ComplaintSerializer(data=data)
		ser.is_valid(raise_exception=True)
		complaint = ser.save(user=request.user, status=ComplaintStatus.OPEN.value)
		return Response(ComplaintSerializer(complaint).data, status=200)


class PaymentIntentAPI(APIView):
	permission_classes = (permissions.IsAuthenticated,)
	throttle_scope = 'orders'

	@extend_schema(request=PaymentIntentSerializer, responses={200: PaymentSerializer}, operation_id='payment_intent')
	@transaction.atomic
	def post(self, request):
		ser = PaymentIntentSerializer(data=request.data)
		ser.is_valid(raise_exception=True)
		ord_id = ser.validated_data["ord_id"]
		provider = ser.validated_data.get("provider") or getattr(settings, 'PAYMENT_PROVIDER', 'MOCK').upper()

		order = Order.objects.filter(ord_id=ord_id, user=request.user).first()
		if not order:
			return Response({"message": "Order not found"}, status=404)
		if order.payment_status.lower() == "paid":
			return Response({"message": "Order already paid"}, status=400)

		if provider.upper() == 'PAYSTACK':
			# Initialize Paystack transaction
			client = PaystackClient()
			amount_minor = int((Decimal(order.total_price) * 100).quantize(Decimal('1')))
			# Use ord_id as reference to ensure idempotency
			init_data = client.initialize(
				email=request.user.email or f"user{request.user.id}@example.com",
				amount_minor=amount_minor,
				reference=order.ord_id,
				currency=order.currency or 'GHS',
			)
			payment = Payment.objects.create(
				order=order,
				user=request.user,
				amount=order.total_price,
				currency=order.currency,
				provider='PAYSTACK',
				status=PaymentStatus.PENDING.value,
				client_secret=init_data.get('access_code') or init_data.get('reference', ''),
				metadata={
					'authorization_url': init_data.get('authorization_url'),
					'reference': init_data.get('reference'),
				},
			)
			return Response(PaymentSerializer(payment).data)
		else:
			payment = Payment.objects.create(
				order=order,
				user=request.user,
				amount=order.total_price,
				currency=order.currency,
				provider='MOCK',
				status=PaymentStatus.PENDING.value,
				client_secret=f"mock_{order.ord_id}_secret",
			)
			return Response(PaymentSerializer(payment).data)


class PaymentConfirmAPI(APIView):
	permission_classes = (permissions.IsAuthenticated,)
	throttle_scope = 'orders'

	@extend_schema(request=PaymentConfirmSerializer, responses={200: PaymentSerializer}, operation_id='payment_confirm')
	@transaction.atomic
	def post(self, request, ord_id: str):
		ser = PaymentConfirmSerializer(data={**request.data, "ord_id": ord_id})
		ser.is_valid(raise_exception=True)

		order = Order.objects.filter(ord_id=ord_id, user=request.user).first()
		if not order:
			return Response({"message": "Order not found"}, status=404)

		payment = Payment.objects.filter(order=order, status=PaymentStatus.PENDING.value).order_by("-created_at").first()
		if not payment:
			return Response({"message": "No pending payment found"}, status=404)

		txn_id = ser.validated_data.get("transaction_id")
		reference = ser.validated_data.get("reference") or payment.metadata.get('reference') if payment.metadata else None

		provider = payment.provider.upper()
		if provider == 'PAYSTACK':
			ref = reference or txn_id or order.ord_id
			client = PaystackClient()
			verify = client.verify(ref)
			status_str = (verify.get('status') or '').lower()
			if status_str != 'success':
				return Response({'message': 'Payment not successful'}, status=400)
			payment.transaction_id = verify.get('reference') or ref
			payment.status = PaymentStatus.SUCCEEDED.value
			payment.metadata = {**(payment.metadata or {}), 'gateway_response': verify.get('gateway_response')}
			payment.save(update_fields=["transaction_id", "status", "metadata", "updated_at"])
		else:
			# Mock verification success
			payment.transaction_id = txn_id or f"mock_{order.ord_id}"
			payment.status = PaymentStatus.SUCCEEDED.value
			payment.save(update_fields=["transaction_id", "status", "updated_at"])

		order.payment_status = "Paid"
		order.status = OrderStatus.CONFIRMED.value
		order.save(update_fields=["payment_status", "status", "updated_at"])

		return Response(PaymentSerializer(payment).data, status=200)


class ChatbotIntentAPI(APIView):
	permission_classes = (permissions.AllowAny,)
	throttle_scope = 'chatbot'

	@extend_schema(
		request=None,
		responses={200: dict},
		operation_id='chatbot_intent',
		description='Classify user message with OpenAI into intents and return extracted entities.'
	)
	def post(self, request):
		message = (request.data or {}).get("message", "")
		if not message:
			return Response({"message": "message is required"}, status=400)
		engine = IntentEngine()
		result = engine.classify(message)
		return Response(result, status=200)


class RestaurantOrdersAPI(APIView):
	"""List orders belonging to the authenticated restaurant owner."""
	permission_classes = (permissions.IsAuthenticated,)
	throttle_scope = 'restaurant'

	@extend_schema(
		parameters=[
			OpenApiParameter(name='status', type=OpenApiTypes.STR, location=OpenApiParameter.QUERY, required=False),
			OpenApiParameter(name='payment_status', type=OpenApiTypes.STR, location=OpenApiParameter.QUERY, required=False),
			OpenApiParameter(name='q', type=OpenApiTypes.STR, location=OpenApiParameter.QUERY, required=False, description='Search by ord_id'),
			OpenApiParameter(name='created_from', type=OpenApiTypes.DATE, location=OpenApiParameter.QUERY, required=False),
			OpenApiParameter(name='created_to', type=OpenApiTypes.DATE, location=OpenApiParameter.QUERY, required=False),
		],
		responses={200: OrderSerializer(many=True)},
		operation_id='restaurant_orders_list',
		description='List orders for the authenticated restaurant owner.'
	)
	def get(self, request):
		restaurant = Restaurant.objects.filter(user=request.user).first()
		if not restaurant and not (request.user.is_staff or request.user.is_superuser):
			return Response({"message": "Restaurant account required"}, status=403)

		qs = Order.objects.all()
		if restaurant:
			qs = qs.filter(restaurant=restaurant)

		status_q = request.query_params.get('status')
		if status_q:
			qs = qs.filter(status__iexact=status_q)

		payment_status = request.query_params.get('payment_status')
		if payment_status:
			qs = qs.filter(payment_status__iexact=payment_status)

		q = request.query_params.get('q')
		if q:
			qs = qs.filter(ord_id__icontains=q)

		created_from = request.query_params.get('created_from')
		created_to = request.query_params.get('created_to')
		if created_from:
			qs = qs.filter(created_at__date__gte=created_from)
		if created_to:
			qs = qs.filter(created_at__date__lte=created_to)

		qs = qs.order_by('-created_at')
		paginator = PageNumberPagination()
		page = paginator.paginate_queryset(qs, request)
		data = OrderSerializer(page or qs, many=True).data
		if page is not None:
			return paginator.get_paginated_response(data)
		return Response(data)


class RestaurantReservationsAPI(APIView):
	"""List reservations belonging to the authenticated restaurant owner."""
	permission_classes = (permissions.IsAuthenticated,)
	throttle_scope = 'restaurant'

	@extend_schema(
		parameters=[
			OpenApiParameter(name='status', type=OpenApiTypes.STR, location=OpenApiParameter.QUERY, required=False),
			OpenApiParameter(name='created_from', type=OpenApiTypes.DATE, location=OpenApiParameter.QUERY, required=False),
			OpenApiParameter(name='created_to', type=OpenApiTypes.DATE, location=OpenApiParameter.QUERY, required=False),
		],
		responses={200: ReservationSerializer(many=True)},
		operation_id='restaurant_reservations_list',
		description='List reservations for the authenticated restaurant owner.'
	)
	def get(self, request):
		restaurant = Restaurant.objects.filter(user=request.user).first()
		if not restaurant and not (request.user.is_staff or request.user.is_superuser):
			return Response({"message": "Restaurant account required"}, status=403)

		qs = Reservation.objects.all()
		if restaurant:
			qs = qs.filter(restaurant=restaurant)

		status_q = request.query_params.get('status')
		if status_q:
			qs = qs.filter(status__iexact=status_q)
		created_from = request.query_params.get('created_from')
		created_to = request.query_params.get('created_to')
		if created_from:
			qs = qs.filter(created_at__date__gte=created_from)
		if created_to:
			qs = qs.filter(created_at__date__lte=created_to)

		qs = qs.order_by('-created_at')
		paginator = PageNumberPagination()
		page = paginator.paginate_queryset(qs, request)
		data = ReservationSerializer(page or qs, many=True).data
		if page is not None:
			return paginator.get_paginated_response(data)
		return Response(data)


class RestaurantOrderUpdateAPI(APIView):
	permission_classes = (permissions.IsAuthenticated,)
	throttle_scope = 'restaurant'

	@extend_schema(request=OrderStatusUpdateSerializer, responses={200: OrderSerializer}, operation_id='restaurant_order_update')
	def patch(self, request, ord_id: str):
		restaurant = Restaurant.objects.filter(user=request.user).first()
		if not restaurant and not (request.user.is_staff or request.user.is_superuser):
			return Response({"message": "Restaurant account required"}, status=403)

		order = Order.objects.filter(ord_id=ord_id).first()
		if not order:
			return Response({"message": "Order not found"}, status=404)
		if restaurant and order.restaurant_id != restaurant.id and not (request.user.is_staff or request.user.is_superuser):
			return Response({"message": "Not authorized"}, status=403)

		ser = OrderStatusUpdateSerializer(data=request.data)
		ser.is_valid(raise_exception=True)
		new_status = ser.validated_data['status']
		# Enforce allowed state transitions
		allowed = {
			OrderStatus.PENDING.value: {OrderStatus.CONFIRMED.value, OrderStatus.CANCELLED.value},
			OrderStatus.CONFIRMED.value: {OrderStatus.PREPARING.value, OrderStatus.CANCELLED.value},
			OrderStatus.PREPARING.value: {OrderStatus.READY.value, OrderStatus.CANCELLED.value},
			OrderStatus.READY.value: {OrderStatus.DISPATCHED.value, OrderStatus.CANCELLED.value},
			OrderStatus.DISPATCHED.value: {OrderStatus.COMPLETED.value},
			OrderStatus.COMPLETED.value: set(),
			OrderStatus.CANCELLED.value: set(),
		}
		current = order.status
		if new_status not in allowed.get(current, set()):
			return Response({
				'message': f'Invalid transition from {current} to {new_status}'
			}, status=400)
		order.status = new_status
		order.save(update_fields=['status', 'updated_at'])
		return Response(OrderSerializer(order).data)


class RestaurantReservationUpdateAPI(APIView):
	permission_classes = (permissions.IsAuthenticated,)
	throttle_scope = 'restaurant'

	@extend_schema(request=ReservationStatusUpdateSerializer, responses={200: ReservationSerializer}, operation_id='restaurant_reservation_update')
	def patch(self, request, pk: int):
		restaurant = Restaurant.objects.filter(user=request.user).first()
		if not restaurant and not (request.user.is_staff or request.user.is_superuser):
			return Response({"message": "Restaurant account required"}, status=403)

		reservation = Reservation.objects.filter(id=pk).first()
		if not reservation:
			return Response({"message": "Reservation not found"}, status=404)
		if restaurant and reservation.restaurant_id != restaurant.id and not (request.user.is_staff or request.user.is_superuser):
			return Response({"message": "Not authorized"}, status=403)

		ser = ReservationStatusUpdateSerializer(data=request.data)
		ser.is_valid(raise_exception=True)
		new_status = ser.validated_data['status']
		# Allowed transitions for reservations
		allowed_r = {
			'PENDING': {'APPROVED', 'CANCELLED'},
			'APPROVED': {'CANCELLED'},
			'CANCELLED': set(),
		}
		current_r = reservation.status
		if new_status not in allowed_r.get(current_r, set()):
			return Response({'message': f'Invalid transition from {current_r} to {new_status}'}, status=400)
		reservation.status = new_status
		reservation.save(update_fields=['status', 'updated_at'])
		# Free up table on cancellation
		if new_status == 'CANCELLED':
			Table.objects.filter(id=reservation.table_id).update(available=True)
		return Response(ReservationSerializer(reservation).data)


class RestaurantDishListCreateAPI(APIView):
	permission_classes = (permissions.IsAuthenticated,)
	throttle_scope = 'restaurant'

	@extend_schema(responses={200: DishSerializer(many=True)}, operation_id='restaurant_dishes_list')
	def get(self, request):
		restaurant = Restaurant.objects.filter(user=request.user).first()
		if not restaurant and not (request.user.is_staff or request.user.is_superuser):
			return Response({"message": "Restaurant account required"}, status=403)
		qs = Dish.objects.all()
		if restaurant:
			qs = qs.filter(restaurant=restaurant)
		q = request.query_params.get('q')
		if q:
			qs = qs.filter(Q(name__icontains=q) | Q(description__icontains=q))
		qs = qs.order_by('name')
		paginator = PageNumberPagination()
		page = paginator.paginate_queryset(qs, request)
		data = DishSerializer(page or qs, many=True).data
		if page is not None:
			return paginator.get_paginated_response(data)
		return Response(data)

	@extend_schema(request=DishCreateUpdateSerializer, responses={200: DishSerializer}, operation_id='restaurant_dishes_create')
	def post(self, request):
		restaurant = Restaurant.objects.filter(user=request.user).first()
		if not restaurant and not (request.user.is_staff or request.user.is_superuser):
			return Response({"message": "Restaurant account required"}, status=403)
		ser = DishCreateUpdateSerializer(data=request.data)
		ser.is_valid(raise_exception=True)
		dish = Dish.objects.create(restaurant=restaurant or Restaurant.objects.first(), **ser.validated_data)
		return Response(DishSerializer(dish).data)


class RestaurantDishDetailAPI(APIView):
	permission_classes = (permissions.IsAuthenticated,)
	throttle_scope = 'restaurant'

	def _get_obj(self, request, pk: int):
		dish = Dish.objects.filter(id=pk).first()
		if not dish:
			return None, Response({"message": "Dish not found"}, status=404)
		restaurant = Restaurant.objects.filter(user=request.user).first()
		if restaurant and dish.restaurant_id != restaurant.id and not (request.user.is_staff or request.user.is_superuser):
			return None, Response({"message": "Not authorized"}, status=403)
		return dish, None

	@extend_schema(responses={200: DishSerializer}, operation_id='restaurant_dishes_retrieve')
	def get(self, request, pk: int):
		dish, error = self._get_obj(request, pk)
		if error:
			return error
		return Response(DishSerializer(dish).data)

	@extend_schema(request=DishCreateUpdateSerializer, responses={200: DishSerializer}, operation_id='restaurant_dishes_update')
	def put(self, request, pk: int):
		dish, error = self._get_obj(request, pk)
		if error:
			return error
		ser = DishCreateUpdateSerializer(dish, data=request.data)
		ser.is_valid(raise_exception=True)
		ser.save()
		return Response(DishSerializer(dish).data)

	@extend_schema(request=DishCreateUpdateSerializer, responses={200: DishSerializer}, operation_id='restaurant_dishes_partial_update')
	def patch(self, request, pk: int):
		dish, error = self._get_obj(request, pk)
		if error:
			return error
		ser = DishCreateUpdateSerializer(dish, data=request.data, partial=True)
		ser.is_valid(raise_exception=True)
		ser.save()
		return Response(DishSerializer(dish).data)

	@extend_schema(responses={204: None}, operation_id='restaurant_dishes_delete')
	def delete(self, request, pk: int):
		dish, error = self._get_obj(request, pk)
		if error:
			return error
		dish.delete()
		return Response(status=204)


class RestaurantTableListCreateAPI(APIView):
	permission_classes = (permissions.IsAuthenticated,)
	throttle_scope = 'restaurant'

	@extend_schema(responses={200: TableSerializer(many=True)}, operation_id='restaurant_tables_list')
	def get(self, request):
		restaurant = Restaurant.objects.filter(user=request.user).first()
		if not restaurant and not (request.user.is_staff or request.user.is_superuser):
			return Response({"message": "Restaurant account required"}, status=403)
		qs = Table.objects.all()
		if restaurant:
			qs = qs.filter(restaurant=restaurant)
		qs = qs.order_by('table_id')
		paginator = PageNumberPagination()
		page = paginator.paginate_queryset(qs, request)
		data = TableSerializer(page or qs, many=True).data
		if page is not None:
			return paginator.get_paginated_response(data)
		return Response(data)

	@extend_schema(request=TableCreateUpdateSerializer, responses={200: TableSerializer}, operation_id='restaurant_tables_create')
	def post(self, request):
		restaurant = Restaurant.objects.filter(user=request.user).first()
		if not restaurant and not (request.user.is_staff or request.user.is_superuser):
			return Response({"message": "Restaurant account required"}, status=403)
		ser = TableCreateUpdateSerializer(data=request.data)
		ser.is_valid(raise_exception=True)
		table = Table.objects.create(restaurant=restaurant or Restaurant.objects.first(), **ser.validated_data)
		return Response(TableSerializer(table).data)


class RestaurantTableDetailAPI(APIView):
	permission_classes = (permissions.IsAuthenticated,)
	throttle_scope = 'restaurant'

	def _get_obj(self, request, pk: int):
		table = Table.objects.filter(id=pk).first()
		if not table:
			return None, Response({"message": "Table not found"}, status=404)
		restaurant = Restaurant.objects.filter(user=request.user).first()
		if restaurant and table.restaurant_id != restaurant.id and not (request.user.is_staff or request.user.is_superuser):
			return None, Response({"message": "Not authorized"}, status=403)
		return table, None

	@extend_schema(responses={200: TableSerializer}, operation_id='restaurant_tables_retrieve')
	def get(self, request, pk: int):
		table, error = self._get_obj(request, pk)
		if error:
			return error
		return Response(TableSerializer(table).data)

	@extend_schema(request=TableCreateUpdateSerializer, responses={200: TableSerializer}, operation_id='restaurant_tables_update')
	def put(self, request, pk: int):
		table, error = self._get_obj(request, pk)
		if error:
			return error
		ser = TableCreateUpdateSerializer(table, data=request.data)
		ser.is_valid(raise_exception=True)
		ser.save()
		return Response(TableSerializer(table).data)

	@extend_schema(request=TableCreateUpdateSerializer, responses={200: TableSerializer}, operation_id='restaurant_tables_partial_update')
	def patch(self, request, pk: int):
		table, error = self._get_obj(request, pk)
		if error:
			return error
		ser = TableCreateUpdateSerializer(table, data=request.data, partial=True)
		ser.is_valid(raise_exception=True)
		ser.save()
		return Response(TableSerializer(table).data)

	@extend_schema(responses={204: None}, operation_id='restaurant_tables_delete')
	def delete(self, request, pk: int):
		table, error = self._get_obj(request, pk)
		if error:
			return error
		table.delete()
		return Response(status=204)
