from django.db import transaction
from django.db.models import Q, Sum, Count
from drf_spectacular.utils import extend_schema, OpenApiParameter, OpenApiExample
from drf_spectacular.types import OpenApiTypes
from rest_framework import permissions, status
from rest_framework.response import Response
from rest_framework.views import APIView
from rest_framework.pagination import PageNumberPagination
from django.conf import settings
import hmac
import hashlib
from decimal import Decimal

from accounts.models import Restaurant, OperationalHours
from accounts.serializers import UserSerializer
from agentic.services import IntentEngine
from api.models import Complaint, Dish, Order, Payment, PaymentRefund, Reservation, Table, SubscriptionPackage, Subscription
from api.serializers import (
	ComplaintSerializer,
	DishSerializer,
	DishCreateUpdateSerializer,
	MenuQuerySerializer,
	OrderSerializer,
	PaymentConfirmSerializer,
	PaymentIntentSerializer,
	PaymentSerializer,
	PaymentRefundSerializer,
	PlaceOrderSerializer,
	ReadonlyReservationSerializer,
	ReservationSerializer,
	TableSerializer,
	TableCreateUpdateSerializer,
	OrderStatusUpdateSerializer,
	ReservationStatusUpdateSerializer,
	OperationalHoursSerializer,
	OperationalHoursCreateUpdateSerializer,
    OperationalHoursBatchUpsertSerializer,
    RestaurantCreateSerializer,
    RestaurantProfileSerializer,
	AdminRestaurantUserSerializer,
	AdminRestaurantListSerializer,
	SubscriptionPackageSerializer,
	SubscriptionSerializer,
)
from leeaicore.sysutils.constants import ComplaintStatus, OrderStatus, PaymentStatus
from leeaicore.sysutils.permissions import IsStaffAdmin
from api.services import PaystackClient, enforce_subscription_limit
from typing import Dict
from knox.models import AuthToken

# Day ordering for consistent Mon→Sun sorting
DAY_ORDER = ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday"]
DAY_INDEX: Dict[str, int] = {d: i for i, d in enumerate(DAY_ORDER)}


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
		# Enforce subscription order limit for the restaurant
		from accounts.models import Restaurant as RestaurantModel
		from api.models import Order as OrderModel
		restaurant = RestaurantModel.objects.get(rid=ser.validated_data["restaurant_rid"])
		current_orders = OrderModel.objects.filter(restaurant=restaurant).count()
		try:
			enforce_subscription_limit(restaurant, kind='orders', current_count=current_orders)
		except ValueError as e:
			return Response({"message": str(e)}, status=403)
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

	@extend_schema(responses={200: ReadonlyReservationSerializer(many=True)}, operation_id='list_reservations')
	def get(self, request):
		qs = Reservation.objects.filter(user=request.user).order_by("-created_at")
		paginator = PageNumberPagination()
		page = paginator.paginate_queryset(qs, request)
		data = ReadonlyReservationSerializer(page or qs, many=True).data
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
		# Enforce subscription reservation limit
		from api.models import Reservation as ReservationModel
		current_reservations = ReservationModel.objects.filter(restaurant=restaurant).count()
		try:
			enforce_subscription_limit(restaurant, kind='reservations', current_count=current_reservations)
		except ValueError as e:
			return Response({"message": str(e)}, status=403)

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


class RestaurantCreateAPI(APIView):
	permission_classes = (permissions.IsAuthenticated,)
	throttle_scope = 'restaurant'

	@extend_schema(request=RestaurantCreateSerializer, responses={200: RestaurantProfileSerializer}, operation_id='create_restaurant')
	def post(self, request):
		ser = RestaurantCreateSerializer(data=request.data, context={"request": request})
		ser.is_valid(raise_exception=True)
		if Restaurant.objects.filter(user=request.user).exists():
			return Response({"message": "Restaurant profile already exists"}, status=400)

		if request.user.is_staff or request.user.is_superuser:
			# Staff can create multiple restaurants
			restaurant = ser.save()
		else:
			restaurant = ser.save(user=request.user)
		return Response(RestaurantProfileSerializer(restaurant).data, status=200)


class RestaurantUpdateAPI(APIView):
	permission_classes = (permissions.IsAuthenticated,)
	throttle_scope = 'restaurant'

	@extend_schema(request=RestaurantProfileSerializer, responses={200: RestaurantProfileSerializer}, operation_id='update_restaurant')
	def put(self, request):
		restaurant = Restaurant.objects.filter(user=request.user).first()
		if not restaurant:
			return Response({"message": "Restaurant profile not found"}, status=404)

		ser = RestaurantProfileSerializer(restaurant, data=request.data, partial=True)
		ser.is_valid(raise_exception=True)
		ser.save()
		return Response(RestaurantProfileSerializer(restaurant).data, status=200)

class RestaurantProfileAPI(APIView):
	permission_classes = (permissions.IsAuthenticated,)
	throttle_scope = 'restaurant'

	@extend_schema(responses={200: RestaurantProfileSerializer}, operation_id='restaurant_profile')
	def get(self, request):
		restaurant = Restaurant.objects.filter(user=request.user).first()
		if not restaurant:
			return Response({"message": "Restaurant profile not found"}, status=404)
		return Response(RestaurantProfileSerializer(restaurant).data, status=200)


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
		parameters=[OpenApiParameter(name='message', type=OpenApiTypes.STR, required=True)],
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


class AdminRestaurantsAPI(APIView):
	"""Admin: list all restaurants."""
	permission_classes = (IsStaffAdmin,)
	throttle_scope = 'admin'

	@extend_schema(
		responses={200: AdminRestaurantListSerializer(many=True)},
		operation_id='admin_restaurants_list',
		description='List all restaurants (admin only), including owner user info and latest subscription.'
	)
	def get(self, request):
		qs = Restaurant.objects.select_related('user').prefetch_related('subscriptions', 'subscriptions__package').all().order_by('name')
		paginator = PageNumberPagination()
		page = paginator.paginate_queryset(qs, request)
		data = AdminRestaurantListSerializer(page or qs, many=True).data
		if page is not None:
			return paginator.get_paginated_response(data)
		return Response(data)


class AdminRestaurantDetailAPI(APIView):
	"""Admin: retrieve a single restaurant by id."""
	permission_classes = (IsStaffAdmin,)
	throttle_scope = 'admin'

	@extend_schema(
		responses={200: RestaurantProfileSerializer},
		operation_id='admin_restaurant_detail',
		description='Retrieve detailed information for a single restaurant (admin only).'
	)
	def get(self, request, pk: int):
		restaurant = Restaurant.objects.select_related('user').filter(id=pk).first()
		if not restaurant:
			return Response({"message": "Restaurant not found"}, status=404)
		return Response(RestaurantProfileSerializer(restaurant).data, status=200)

	@extend_schema(
		responses={200: {"message": "Restaurant deleted (soft) and user access revoked"}},
		operation_id='admin_restaurant_delete',
		description='Soft delete a restaurant by marking its owner inactive and deleted.',
	)
	def delete(self, request, pk: int):
		restaurant = Restaurant.objects.select_related('user').filter(id=pk).first()
		if not restaurant:
			return Response({"message": "Restaurant not found"}, status=404)
		user = restaurant.user
		user.deleted = True
		user.is_active = False
		user.save(update_fields=["deleted", "is_active", "updated_at"] if hasattr(user, "updated_at") else ["deleted", "is_active"])
		AuthToken.objects.filter(user=user).delete()
		return Response({"message": "Restaurant deleted (soft) and user access revoked"}, status=200)


class AdminOrdersAPI(APIView):
	"""Admin: list all orders with basic filtering."""
	permission_classes = (IsStaffAdmin,)
	throttle_scope = 'admin'

	@extend_schema(
		parameters=[
			OpenApiParameter(name='status', type=OpenApiTypes.STR, location=OpenApiParameter.QUERY, required=False),
			OpenApiParameter(name='payment_status', type=OpenApiTypes.STR, location=OpenApiParameter.QUERY, required=False),
			OpenApiParameter(name='q', type=OpenApiTypes.STR, location=OpenApiParameter.QUERY, required=False, description='Search by ord_id'),
		],
		responses={200: OrderSerializer(many=True)},
		operation_id='admin_orders_list',
		description='List all orders in the system (admin only).'
	)
	def get(self, request):
		qs = Order.objects.all()
		status_q = request.query_params.get('status')
		if status_q:
			qs = qs.filter(status__iexact=status_q)
		payment_status = request.query_params.get('payment_status')
		if payment_status:
			qs = qs.filter(payment_status__iexact=payment_status)
		q = request.query_params.get('q')
		if q:
			qs = qs.filter(ord_id__icontains=q)
		qs = qs.order_by('-created_at')
		paginator = PageNumberPagination()
		page = paginator.paginate_queryset(qs, request)
		data = OrderSerializer(page or qs, many=True).data
		if page is not None:
			return paginator.get_paginated_response(data)
		return Response(data)


class AdminReservationsAPI(APIView):
	"""Admin: list all reservations."""
	permission_classes = (IsStaffAdmin,)
	throttle_scope = 'admin'

	@extend_schema(
		parameters=[
			OpenApiParameter(name='status', type=OpenApiTypes.STR, location=OpenApiParameter.QUERY, required=False),
		],
		responses={200: ReservationSerializer(many=True)},
		operation_id='admin_reservations_list',
		description='List all reservations in the system (admin only).'
	)
	def get(self, request):
		qs = Reservation.objects.all()
		status_q = request.query_params.get('status')
		if status_q:
			qs = qs.filter(status__iexact=status_q)
		qs = qs.order_by('-created_at')
		paginator = PageNumberPagination()
		page = paginator.paginate_queryset(qs, request)
		data = ReservationSerializer(page or qs, many=True).data
		if page is not None:
			return paginator.get_paginated_response(data)
		return Response(data)


class AdminTablesAPI(APIView):
	"""Admin: list all tables."""
	permission_classes = (IsStaffAdmin,)
	throttle_scope = 'admin'

	@extend_schema(
		responses={200: TableSerializer(many=True)},
		operation_id='admin_tables_list',
		description='List all tables in the system (admin only).'
	)
	def get(self, request):
		qs = Table.objects.all().order_by('restaurant_id', 'name')
		paginator = PageNumberPagination()
		page = paginator.paginate_queryset(qs, request)
		data = TableSerializer(page or qs, many=True).data
		if page is not None:
			return paginator.get_paginated_response(data)
		return Response(data)


class AdminDishesAPI(APIView):
	"""Admin: list all dishes."""
	permission_classes = (IsStaffAdmin,)
	throttle_scope = 'admin'

	@extend_schema(
		responses={200: DishSerializer(many=True)},
		operation_id='admin_dishes_list',
		description='List all dishes in the system (admin only).'
	)
	def get(self, request):
		qs = Dish.objects.all().order_by('restaurant_id', 'name')
		paginator = PageNumberPagination()
		page = paginator.paginate_queryset(qs, request)
		data = DishSerializer(page or qs, many=True).data
		if page is not None:
			return paginator.get_paginated_response(data)
		return Response(data)


class AdminPaymentsAPI(APIView):
	"""Admin: list all payments."""
	permission_classes = (IsStaffAdmin,)
	throttle_scope = 'admin'

	@extend_schema(
		parameters=[
			OpenApiParameter(name='status', type=OpenApiTypes.STR, location=OpenApiParameter.QUERY, required=False),
		],
		responses={200: PaymentSerializer(many=True)},
		operation_id='admin_payments_list',
		description='List all payments in the system (admin only) with summary info.'
	)
	def get(self, request):
		qs = Payment.objects.all()
		status_q = request.query_params.get('status')
		if status_q:
			qs = qs.filter(status__iexact=status_q)
		qs = qs.order_by('-created_at')

		# Compute summary across all payments (ignores pagination)
		all_payments = Payment.objects.all()
		total_revenue = all_payments.filter(status=PaymentStatus.SUCCEEDED.value).aggregate(Sum('amount'))['amount__sum'] or 0
		failed_payments = all_payments.exclude(status=PaymentStatus.SUCCEEDED.value).count()
		refunds_issued = PaymentRefund.objects.aggregate(Sum('amount'))['amount__sum'] or 0
		active_subscriptions = 0
		summary = {
			"total_revenue": total_revenue,
			"failed_payments": failed_payments,
			"refunds_issued": refunds_issued,
			"active_subscriptions": active_subscriptions,
		}

		paginator = PageNumberPagination()
		page = paginator.paginate_queryset(qs, request)
		items = PaymentSerializer(page or qs, many=True).data
		if page is not None:
			# Wrap paginated data with summary
			paginated = paginator.get_paginated_response(items)
			paginated.data['summary'] = summary
			return paginated
		return Response({"summary": summary, "results": items})


class AdminRestaurantUsersAPI(APIView):
	"""Admin: list users associated with a restaurant (currently owner only)."""
	permission_classes = (IsStaffAdmin,)
	throttle_scope = 'admin'

	@extend_schema(
		responses={200: AdminRestaurantUserSerializer(many=True)},
		operation_id='admin_restaurant_users',
		description='List users associated with the restaurant (owner user for now).'
	)
	def get(self, request, pk: int):
		restaurant = Restaurant.objects.select_related('user').filter(id=pk).first()
		if not restaurant:
			return Response({"message": "Restaurant not found"}, status=404)
		users = [restaurant.user]
		data = AdminRestaurantUserSerializer(users, many=True).data
		return Response(data, status=200)


class AdminRestaurantPaymentsAPI(APIView):
	"""Admin: list payments associated with a restaurant."""
	permission_classes = (IsStaffAdmin,)
	throttle_scope = 'admin'

	@extend_schema(
		responses={200: PaymentSerializer(many=True)},
		operation_id='admin_restaurant_payments',
		description='List all payments associated with a given restaurant (admin only).'
	)
	def get(self, request, pk: int):
		restaurant = Restaurant.objects.filter(id=pk).first()
		if not restaurant:
			return Response({"message": "Restaurant not found"}, status=404)
		qs = Payment.objects.filter(order__restaurant=restaurant).order_by('-created_at')
		paginator = PageNumberPagination()
		page = paginator.paginate_queryset(qs, request)
		data = PaymentSerializer(page or qs, many=True).data
		if page is not None:
			return paginator.get_paginated_response(data)
		return Response(data)


class AdminRestaurantSubscriptionsAPI(APIView):
	"""Admin: list subscriptions for a single restaurant with summary."""
	permission_classes = (IsStaffAdmin,)
	throttle_scope = 'admin'

	@extend_schema(
		responses={200: OpenApiTypes.OBJECT},
		operation_id='admin_restaurant_subscriptions',
		description='List subscriptions for a restaurant (admin only), with a billing summary.',
		examples=[
			OpenApiExample(
				'AdminRestaurantSubscriptionsExample',
				value={
					"summary": {
						"next_billing_date": "2025-12-31",
						"monthly_amount": "199.99",
						"outstanding_balance": "80.00",
						"last_payment": {
							"amount": "199.99",
							"currency": "GHC",
							"transaction_reference": "sub_42_3_ABC123",
							"start_date": "2025-12-01",
							"end_date": "2025-12-31",
							"status": "ACTIVE",
						},
					},
					"results": [
						{
							"name": "Pro Plan",
							"start_date": "2025-12-01",
							"end_date": "2025-12-31",
							"transaction_reference": "sub_42_3_ABC123",
							"amount": "199.99",
							"currency": "GHC",
							"payment_status": "ACTIVE",
						}
					],
				},
			),
		],
	)
	def get(self, request, pk: int):
		from datetime import timedelta
		from django.utils import timezone

		restaurant = Restaurant.objects.filter(id=pk).first()
		if not restaurant:
			return Response({"message": "Restaurant not found"}, status=404)

		qs = Subscription.objects.filter(restaurant=restaurant).select_related('package').order_by('-start_date', '-created_at')
		subs_data = []
		for sub in qs:
			amount = sub.package.price if sub.package else None
			currency = sub.package.currency if sub.package else None
			subs_data.append({
				"name": sub.package.name if sub.package else None,
				"start_date": sub.start_date,
				"end_date": sub.end_date,
				"transaction_reference": sub.paystack_reference,
				"amount": amount,
				"currency": currency,
				"payment_status": sub.status,
			})

		# Build summary based on the most recent subscription
		latest = qs.first()
		summary = {
			"next_billing_date": None,
			"monthly_amount": None,
			"outstanding_balance": None,
			"last_payment": None,
		}
		if latest and latest.package:
			monthly_amount = latest.package.price
			currency = latest.package.currency
			start_date = latest.start_date
			end_date = latest.end_date
			# If end_date is missing, assume a 30-day period from start_date
			if not end_date and start_date:
				end_date = start_date + timedelta(days=30)
				next_billing_date = end_date
			elif end_date:
				next_billing_date = end_date
			else:
				next_billing_date = None

			# Outstanding balance based on days used vs left in current period
			outstanding_balance = None
			if start_date and end_date and latest.status == 'ACTIVE':
				period_days = (end_date - start_date).days or 1
				# Use current local date for usage calculation
				today = timezone.localdate()
				if today < start_date:
					used_days = 0
				elif today >= end_date:
					used_days = period_days
				else:
					used_days = (today - start_date).days
				days_left = max(period_days - used_days, 0)
				# daily rate * days_left
				if period_days > 0:
					# monthly_amount is Decimal, keep precision
					from decimal import Decimal, ROUND_HALF_UP
					daily_rate = (monthly_amount / Decimal(period_days)) if period_days else Decimal('0')
					outstanding_balance = (daily_rate * days_left).quantize(Decimal('0.01'), rounding=ROUND_HALF_UP)

			last_payment = {
				"amount": monthly_amount,
				"currency": currency,
				"transaction_reference": latest.paystack_reference,
				"start_date": start_date,
				"end_date": end_date,
				"status": latest.status,
			}

			summary.update({
				"next_billing_date": next_billing_date,
				"monthly_amount": monthly_amount,
				"outstanding_balance": outstanding_balance,
				"last_payment": last_payment,
			})

		return Response({
			"summary": summary,
			"results": subs_data,
		})


class PaymentRefundAPI(APIView):
	"""Issue a refund for a successful payment and record it."""
	permission_classes = (permissions.IsAuthenticated,)
	throttle_scope = 'orders'

	@extend_schema(
		request=PaymentRefundSerializer,
		responses={200: PaymentRefundSerializer},
		operation_id='payment_refund',
		description='Issue a refund for a successful payment. Only admins/staff may refund payments.'
	)
	@transaction.atomic
	def post(self, request):
		ser = PaymentRefundSerializer(data=request.data)
		ser.is_valid(raise_exception=True)
		payment: Payment = ser.validated_data["payment"]
		amount = ser.validated_data["amount"]
		reason = ser.validated_data.get("reason")
		# Authorization: only admin/staff can refund
		is_admin = request.user.is_staff or request.user.is_superuser
		if not is_admin:
			return Response({"message": "Not authorized to refund this payment"}, status=403)

		refund = PaymentRefund.objects.create(
			payment=payment,
			user=payment.user,
			initiated_by=request.user,
			amount=amount,
			reason=reason,
			status='COMPLETED',
		)
		# Update payment metadata to reflect refund
		meta = payment.metadata or {}
		refunds_meta = meta.get('refunds', [])
		refunds_meta.append({
			'id': refund.id,
			'amount': str(refund.amount),
			'reason': refund.reason,
			'created_at': refund.created_at.isoformat(),
		})
		meta['refunds'] = refunds_meta
		payment.metadata = meta
		payment.save(update_fields=["metadata", "updated_at"] if hasattr(payment, "updated_at") else ["metadata"])

		return Response(PaymentRefundSerializer(refund).data, status=200)


class AdminSubscriptionPackageAPI(APIView):
	"""Admin: manage subscription packages/plans."""
	permission_classes = (IsStaffAdmin,)
	throttle_scope = 'admin'

	@extend_schema(
		responses={200: SubscriptionPackageSerializer(many=True)},
		operation_id='admin_subscription_packages_list',
		description='List all subscription packages.'
	)
	def get(self, request):
		qs = SubscriptionPackage.objects.all().order_by('price')
		return Response(SubscriptionPackageSerializer(qs, many=True).data)

	@extend_schema(
		request=SubscriptionPackageSerializer,
		responses={201: SubscriptionPackageSerializer},
		operation_id='admin_subscription_packages_create',
		description='Create a new subscription package.'
	)
	def post(self, request):
		ser = SubscriptionPackageSerializer(data=request.data)
		ser.is_valid(raise_exception=True)
		pkg = ser.save()
		return Response(SubscriptionPackageSerializer(pkg).data, status=201)


class AdminSubscriptionsAPI(APIView):
	"""Admin: list all subscriptions."""
	permission_classes = (IsStaffAdmin,)
	throttle_scope = 'admin'

	@extend_schema(
		responses={200: SubscriptionSerializer(many=True)},
		operation_id='admin_subscriptions_list',
		description='List all restaurant subscriptions.'
	)
	def get(self, request):
		qs = Subscription.objects.select_related('restaurant', 'package').all().order_by('-created_at')
		return Response(SubscriptionSerializer(qs, many=True).data)


class RestaurantSubscriptionAPI(APIView):
	"""Restaurant: subscribe to a package and initialize Paystack payment."""
	permission_classes = (permissions.IsAuthenticated,)
	throttle_scope = 'restaurant'

	@extend_schema(
		request=SubscriptionSerializer,
		responses={200: dict},
		operation_id='restaurant_subscribe',
		description='Subscribe the authenticated restaurant to a package and initialize Paystack payment.'
	)
	@transaction.atomic
	def post(self, request):
		restaurant = Restaurant.objects.filter(user=request.user).first()
		if not restaurant:
			return Response({"message": "Restaurant profile not found"}, status=404)

		ser = SubscriptionSerializer(data=request.data)
		ser.is_valid(raise_exception=True)
		package: SubscriptionPackage = ser.validated_data['package']

		# Initialize Paystack transaction for subscription
		client = PaystackClient()
		amount_minor = int((package.price * 100).quantize(Decimal('1')))
		ref = f"sub_{restaurant.id}_{package.id}"
		init_data = client.initialize(
			email=request.user.email or f"user{request.user.id}@example.com",
			amount_minor=amount_minor,
			reference=ref,
			currency=package.currency or 'GHS',
		)

		sub = Subscription.objects.create(
			restaurant=restaurant,
			package=package,
			status='ACTIVE',
			paystack_reference=init_data.get('reference') or ref,
		)

		return Response({
			"subscription": SubscriptionSerializer(sub).data,
			"paystack": {
				"authorization_url": init_data.get('authorization_url'),
				"access_code": init_data.get('access_code'),
				"reference": init_data.get('reference') or ref,
			},
		})


class SubscriptionConfirmAPI(APIView):
	"""Confirm a subscription payment via Paystack and finalize the subscription."""
	permission_classes = (permissions.IsAuthenticated,)
	throttle_scope = 'restaurant'

	@extend_schema(
		request=None,
		responses={200: SubscriptionSerializer},
		operation_id='subscription_confirm',
		description='Confirm a Paystack subscription payment using a reference and activate the subscription.',
		parameters=[
			OpenApiParameter(name='reference', type=OpenApiTypes.STR, location=OpenApiParameter.QUERY, required=True),
		],
	)
	@transaction.atomic
	def post(self, request):
		ref = request.query_params.get('reference')
		if not ref:
			return Response({"message": "reference is required"}, status=400)

		restaurant = Restaurant.objects.filter(user=request.user).first()
		if not restaurant:
			return Response({"message": "Restaurant profile not found"}, status=404)

		sub = Subscription.objects.filter(restaurant=restaurant, paystack_reference=ref).order_by('-created_at').first()
		if not sub:
			return Response({"message": "Subscription not found for this reference"}, status=404)
		# Prevent multiple activations or changes on non-pending subscriptions
		if sub.status == 'ACTIVE':
			return Response({"message": "Subscription already active"}, status=400)
		if sub.status == 'CANCELLED':
			return Response({"message": "Subscription is cancelled"}, status=400)

		client = PaystackClient()
		verify = client.verify(ref)
		status_str = (verify.get('status') or '').lower()
		if status_str != 'success':
			return Response({'message': 'Subscription payment not successful'}, status=400)

		# Set dates based on actual Paystack payment timestamp to ensure idempotency
		from django.utils.dateparse import parse_datetime
		from django.utils import timezone
		from datetime import timedelta
		paid_at_str = verify.get('paid_at') or verify.get('transaction_date')
		paid_at = parse_datetime(paid_at_str) if paid_at_str else timezone.now()
		if timezone.is_naive(paid_at):
			paid_at = timezone.make_aware(paid_at, timezone.get_current_timezone())
		paid_at = timezone.localtime(paid_at)
		start_date = paid_at.date()
		end_date = start_date + timedelta(days=30)

		sub.status = 'ACTIVE'
		sub.start_date = start_date
		sub.end_date = end_date
		sub.save(update_fields=['status', 'start_date', 'end_date', 'updated_at'])

		return Response(SubscriptionSerializer(sub).data, status=200)


class PaystackWebhookAPI(APIView):
	"""Handle Paystack webhooks for payments and subscriptions."""
	permission_classes = (permissions.AllowAny,)
	throttle_scope = 'orders'

	@extend_schema(
		request=None,
		responses={200: dict},
		operation_id='paystack_webhook',
		description='Paystack webhook endpoint to process payment and subscription events.',
	)
	def post(self, request):
		# Validate Paystack signature
		signature = request.headers.get('X-Paystack-Signature') or request.META.get('HTTP_X_PAYSTACK_SIGNATURE')
		if not signature:
			return Response({"message": "Missing Paystack signature"}, status=400)

		secret = getattr(settings, 'PAYSTACK_SECRET_KEY', '')
		body_bytes = request.body or b''
		computed = hmac.new(secret.encode('utf-8'), body_bytes, hashlib.sha512).hexdigest()
		if not hmac.compare_digest(computed, signature):
			return Response({"message": "Invalid signature"}, status=400)

		event = request.data.get('event')
		data = request.data.get('data') or {}
		if not event or not data:
			return Response({"message": "Invalid payload"}, status=400)

		ref = data.get('reference') or data.get('reference_code')
		if not ref:
			return Response({"message": "Missing reference in payload"}, status=400)

		# Handle successful charge events
		if event == 'charge.success':
			status_str = (data.get('status') or '').lower()
			if status_str == 'success':
				# First, try to match a normal Payment
				payment = Payment.objects.filter(transaction_id=ref).first() or Payment.objects.filter(metadata__reference=ref).first()
				if payment and payment.status != PaymentStatus.SUCCEEDED.value:
					payment.status = PaymentStatus.SUCCEEDED.value
					payment.transaction_id = ref
					payment.save(update_fields=["status", "transaction_id", "updated_at"])
					order = payment.order
					order.payment_status = "Paid"
					order.status = OrderStatus.CONFIRMED.value
					order.save(update_fields=["payment_status", "status", "updated_at"])

				# Then, try to match a Subscription
				from api.models import Subscription as SubscriptionModel
				sub = SubscriptionModel.objects.filter(paystack_reference=ref).order_by('-created_at').first()
				if sub and sub.status != 'ACTIVE':
					# Reuse the same date logic as SubscriptionConfirmAPI
					from django.utils.dateparse import parse_datetime
					from django.utils import timezone
					from datetime import timedelta
					paid_at_str = data.get('paid_at') or data.get('transaction_date')
					paid_at = parse_datetime(paid_at_str) if paid_at_str else timezone.now()
					if timezone.is_naive(paid_at):
						paid_at = timezone.make_aware(paid_at, timezone.get_current_timezone())
					paid_at = timezone.localtime(paid_at)
					start_date = paid_at.date()
					end_date = start_date + timedelta(days=30)
					sub.status = 'ACTIVE'
					sub.start_date = start_date
					sub.end_date = end_date
					sub.save(update_fields=['status', 'start_date', 'end_date', 'updated_at'])

		return Response({"message": "ok"}, status=200)


class AdminAnalyticsAPI(APIView):
	"""Admin: high-level analytics for the platform."""
	permission_classes = (IsStaffAdmin,)
	throttle_scope = 'admin'

	@extend_schema(
		responses={
			200: OpenApiTypes.OBJECT,
		},
		operation_id='admin_analytics',
		description='Platform-wide analytics summary for admins: revenue, volumes, top vendors, and channel distribution.',
		examples=[
			OpenApiExample(
				'AdminAnalyticsExample',
				value={
					"summary": {
						"active_restaurants": 12,
						"total_revenue": "12345.67",
						"total_customers": 340,
						"total_bookings": 210,
						"total_orders": 580,
						"active_subscriptions": 9,
						"pending_refund_requests": 3,
						"total_users": 150,
						"total_reservations": 220,
						"total_customers": 340,
					},
					"volumes_this_week": [
						{"day": "2025-12-01", "weekday": "Mon", "orders": 25, "reservations": 10},
						{"day": "2025-12-02", "weekday": "Tue", "orders": 30, "reservations": 8},
					],
					"top_vendors": [
						{"id": 1, "vendor_name": "Pizza Palace", "revenue": "4500.00"},
						{"id": 2, "vendor_name": "Sushi Corner", "revenue": "3200.00"},
					],
					"channels": {
						"whatsapp": 45,
						"web": 25,
						"Instagram": 10,
						"Messenger": 5,
						"other": 15,
					},
				},
			),
		],
	)
	def get(self, request):
		from django.utils import timezone
		from datetime import timedelta

		now = timezone.now()
		start_of_week = now - timedelta(days=now.weekday())
		start_of_week = start_of_week.replace(hour=0, minute=0, second=0, microsecond=0)

		# Summary
		active_restaurants = Restaurant.objects.filter(is_suspended=False, user__is_active=True, user__deleted=False).count()
		total_users = Restaurant.objects.values('user_id').distinct().count()
		total_orders = Order.objects.count()
		total_reservations = Reservation.objects.count()
		total_revenue_processed = Payment.objects.filter(status=PaymentStatus.SUCCEEDED.value).aggregate(Sum('amount'))['amount__sum'] or 0
		active_subscriptions = Subscription.objects.filter(status='ACTIVE').count()
		pending_refund_requests = PaymentRefund.objects.filter(status='PENDING').count()
		total_customers = Order.objects.values('user_id').distinct().count()

		summary = {
			"active_restaurants": active_restaurants,
			"total_users": total_users,
			"total_orders": total_orders,
			"total_reservations": total_reservations,
			"total_revenue_processed": total_revenue_processed,
			"active_subscriptions": active_subscriptions,
			"pending_refund_requests": pending_refund_requests,
			"total_customers": total_customers,
		}

		# Volumes this week (by day)
		orders_week = (
			Order.objects.filter(created_at__gte=start_of_week)
			.extra(select={"day": "DATE(created_at)"})
			.values("day")
			.annotate(count=Count("id"))
		)
		reservations_week = (
			Reservation.objects.filter(created_at__gte=start_of_week)
			.extra(select={"day": "DATE(created_at)"})
			.values("day")
			.annotate(count=Count("id"))
		)
		orders_by_day = {str(row["day"]): row["count"] for row in orders_week}
		reservations_by_day = {str(row["day"]): row["count"] for row in reservations_week}

		volumes_this_week = []
		for i in range(7):
			day = start_of_week + timedelta(days=i)
			key = str(day.date())
			volumes_this_week.append({
				"day": key,
				"weekday": day.strftime('%a'),
				"orders": orders_by_day.get(key, 0),
				"reservations": reservations_by_day.get(key, 0),
			})

		# Top vendors by revenue
		top_vendors_qs = (
			Payment.objects.filter(status=PaymentStatus.SUCCEEDED.value)
			.values("order__restaurant_id", "order__restaurant__name")
			.annotate(revenue=Sum("amount"))
			.order_by("-revenue")[:10]
		)
		top_vendors = [
			{
				"id": row["order__restaurant_id"],
				"vendor_name": row["order__restaurant__name"],
				"revenue": row["revenue"],
			}
			for row in top_vendors_qs
		]

		channels = {
			"whatsapp": 45,
			"web": 25,
			"Instagram": 10,
			"Messenger": 5,
			"other": 15,
		}

		return Response({
			"summary": summary,
			"volumes_this_week": volumes_this_week,
			"top_vendors": top_vendors,
			"channels": channels,
		})


class AdminRestaurantSuspendAPI(APIView):
	"""Admin: suspend or unsuspend a restaurant's owner account."""
	permission_classes = (IsStaffAdmin,)
	throttle_scope = 'admin'

	@extend_schema(
		request=OpenApiTypes.OBJECT,
		responses={200: dict},
		operation_id='admin_restaurant_suspend',
		description='Suspend a restaurant by disabling its owner user and revoking tokens. Expects a JSON body with "reason".',
	)
	def post(self, request, pk: int):
		restaurant = Restaurant.objects.select_related('user').filter(id=pk).first()
		if not restaurant:
			return Response({"message": "Restaurant not found"}, status=404)
		reason = (request.data or {}).get('reason') or ''
		user = restaurant.user
		user.is_active = False
		user.save(update_fields=["is_active", "updated_at"] if hasattr(user, "updated_at") else ["is_active"])
		restaurant.is_suspended = True
		restaurant.suspension_reason = reason
		restaurant.save(update_fields=["is_suspended", "suspension_reason", "updated_at"] if hasattr(restaurant, "updated_at") else ["is_suspended", "suspension_reason"])
		AuthToken.objects.filter(user=user).delete()
		return Response({"message": "Restaurant suspended and user tokens revoked", "reason": reason}, status=200)


class AdminRestaurantUnsuspendAPI(APIView):
	"""Admin: unsuspend a restaurant's owner account."""
	permission_classes = (IsStaffAdmin,)
	throttle_scope = 'admin'

	@extend_schema(
		request=None,
		responses={200: dict},
		operation_id='admin_restaurant_unsuspend',
		description='Unsuspend a restaurant by re-enabling its owner user (if not deleted).',
	)
	def post(self, request, pk: int):
		restaurant = Restaurant.objects.select_related('user').filter(id=pk).first()
		if not restaurant:
			return Response({"message": "Restaurant not found"}, status=404)
		user = restaurant.user
		if getattr(user, 'deleted', False):
			return Response({"message": "Cannot unsuspend a deleted user"}, status=400)
		user.is_active = True
		user.save(update_fields=["is_active", "updated_at"] if hasattr(user, "updated_at") else ["is_active"])
		restaurant.is_suspended = False
		restaurant.suspension_reason = None
		restaurant.save(update_fields=["is_suspended", "suspension_reason", "updated_at"] if hasattr(restaurant, "updated_at") else ["is_suspended", "suspension_reason"])
		return Response({"message": "Restaurant unsuspended and user re-enabled"}, status=200)


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
		# Enforce subscription dish limit (only for non-staff restaurant accounts)
		if restaurant and not (request.user.is_staff or request.user.is_superuser):
			current_dishes = Dish.objects.filter(restaurant=restaurant).count()
			try:
				enforce_subscription_limit(restaurant, kind='dishes', current_count=current_dishes)
			except ValueError as e:
				return Response({"message": str(e)}, status=403)
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
		# Enforce subscription table limit (only for non-staff restaurant accounts)
		if restaurant and not (request.user.is_staff or request.user.is_superuser):
			current_tables = Table.objects.filter(restaurant=restaurant).count()
			try:
				enforce_subscription_limit(restaurant, kind='tables', current_count=current_tables)
			except ValueError as e:
				return Response({"message": str(e)}, status=403)
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


class RestaurantOperationalHoursListCreateAPI(APIView):
	permission_classes = (permissions.IsAuthenticated,)
	throttle_scope = 'restaurant'

	@extend_schema(
		responses={200: OperationalHoursSerializer(many=True)},
		operation_id='restaurant_operational_hours_list',
		description='List operational hours for the authenticated restaurant owner.',
	)
	def get(self, request):
		restaurant = Restaurant.objects.filter(user=request.user).first()
		if not restaurant and not (request.user.is_staff or request.user.is_superuser):
			return Response({"message": "Restaurant account required"}, status=403)
		qs = OperationalHours.objects.all()
		if restaurant:
			qs = qs.filter(restaurant=restaurant)
		items = list(qs)
		items.sort(key=lambda oh: DAY_INDEX.get(oh.day_of_week, 99))
		return Response(OperationalHoursSerializer(items, many=True).data)

	@extend_schema(
		request=OperationalHoursCreateUpdateSerializer,
		responses={200: OperationalHoursSerializer},
		operation_id='restaurant_operational_hours_create',
		examples=[
			OpenApiExample(
				'Create Monday Hours',
				value={"day_of_week": "Monday", "open_time": "09:00:00", "close_time": "17:00:00"},
			)
		]
	)
	def post(self, request):
		restaurant = Restaurant.objects.filter(user=request.user).first()
		if not restaurant and not (request.user.is_staff or request.user.is_superuser):
			return Response({"message": "Restaurant account required"}, status=403)
		ser = OperationalHoursCreateUpdateSerializer(data=request.data)
		ser.is_valid(raise_exception=True)
		oh = OperationalHours.objects.create(restaurant=restaurant or Restaurant.objects.first(), **ser.validated_data)
		return Response(OperationalHoursSerializer(oh).data)


class RestaurantOperationalHoursDetailAPI(APIView):
	permission_classes = (permissions.IsAuthenticated,)
	throttle_scope = 'restaurant'

	def _get_obj(self, request, pk: int):
		oh = OperationalHours.objects.filter(id=pk).first()
		if not oh:
			return None, Response({"message": "Operational hours not found"}, status=404)
		restaurant = Restaurant.objects.filter(user=request.user).first()
		if restaurant and oh.restaurant_id != restaurant.id and not (request.user.is_staff or request.user.is_superuser):
			return None, Response({"message": "Not authorized"}, status=403)
		return oh, None

	@extend_schema(responses={200: OperationalHoursSerializer}, operation_id='restaurant_operational_hours_retrieve')
	def get(self, request, pk: int):
		oh, error = self._get_obj(request, pk)
		if error:
			return error
		return Response(OperationalHoursSerializer(oh).data)

	@extend_schema(
		request=OperationalHoursCreateUpdateSerializer,
		responses={200: OperationalHoursSerializer},
		operation_id='restaurant_operational_hours_update',
		examples=[
			OpenApiExample(
				'Update Friday Hours',
				value={"day_of_week": "Friday", "open_time": "10:00:00", "close_time": "18:00:00"},
			)
		]
	)
	def put(self, request, pk: int):
		oh, error = self._get_obj(request, pk)
		if error:
			return error
		ser = OperationalHoursCreateUpdateSerializer(oh, data=request.data)
		ser.is_valid(raise_exception=True)
		ser.save()
		return Response(OperationalHoursSerializer(oh).data)

	@extend_schema(
		request=OperationalHoursCreateUpdateSerializer,
		responses={200: OperationalHoursSerializer},
		operation_id='restaurant_operational_hours_partial_update'
	)
	def patch(self, request, pk: int):
		oh, error = self._get_obj(request, pk)
		if error:
			return error
		ser = OperationalHoursCreateUpdateSerializer(oh, data=request.data, partial=True)
		ser.is_valid(raise_exception=True)
		ser.save()
		return Response(OperationalHoursSerializer(oh).data)

	@extend_schema(responses={204: None}, operation_id='restaurant_operational_hours_delete')
	def delete(self, request, pk: int):
		oh, error = self._get_obj(request, pk)
		if error:
			return error
		oh.delete()
		return Response(status=204)


class RestaurantOperationalHoursBatchAPI(APIView):
	permission_classes = (permissions.IsAuthenticated,)
	throttle_scope = 'restaurant'

	@extend_schema(
		request=OperationalHoursBatchUpsertSerializer,
		responses={200: OperationalHoursSerializer(many=True)},
		operation_id='restaurant_operational_hours_batch_upsert',
		description='Batch upsert operational hours for the authenticated restaurant. Use closed=true to remove a day.',
		examples=[
			OpenApiExample(
				'Upsert Full Week',
				value={
					"days": [
						{"day_of_week": "Monday", "open_time": "09:00:00", "close_time": "17:00:00"},
						{"day_of_week": "Tuesday", "open_time": "09:00:00", "close_time": "17:00:00"},
						{"day_of_week": "Wednesday", "open_time": "09:00:00", "close_time": "17:00:00"},
						{"day_of_week": "Thursday", "open_time": "09:00:00", "close_time": "17:00:00"},
						{"day_of_week": "Friday", "open_time": "09:00:00", "close_time": "17:00:00"},
						{"day_of_week": "Saturday", "open_time": "10:00:00", "close_time": "14:00:00"},
						{"day_of_week": "Sunday", "closed": True}
					]
				}
			)
		]
	)
	@transaction.atomic
	def post(self, request):
		ser = OperationalHoursBatchUpsertSerializer(data=request.data)
		ser.is_valid(raise_exception=True)
		restaurant = Restaurant.objects.filter(user=request.user).first()
		if not restaurant and not (request.user.is_staff or request.user.is_superuser):
			return Response({"message": "Restaurant account required"}, status=403)

		for item in ser.validated_data['days']:
			day = item['day_of_week']
			closed = item.get('closed', False)
			if closed:
				OperationalHours.objects.filter(restaurant=restaurant, day_of_week=day).delete()
				continue
			open_time = item['open_time']
			close_time = item['close_time']
			OperationalHours.objects.update_or_create(
				restaurant=restaurant,
				day_of_week=day,
				defaults={"open_time": open_time, "close_time": close_time}
			)

		qs = list(OperationalHours.objects.filter(restaurant=restaurant))
		qs.sort(key=lambda oh: DAY_INDEX.get(oh.day_of_week, 99))
		return Response(OperationalHoursSerializer(qs, many=True).data)
