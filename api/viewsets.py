from django.db import transaction
from django.db.models import Q
from drf_spectacular.utils import extend_schema, OpenApiParameter
from drf_spectacular.types import OpenApiTypes
from rest_framework import permissions, status
from rest_framework.response import Response
from rest_framework.views import APIView

from accounts.models import Restaurant
from agentic.services import IntentEngine
from api.models import Complaint, Dish, Order, Payment, Reservation, Table
from api.serializers import (
	ComplaintSerializer,
	DishSerializer,
	MenuQuerySerializer,
	OrderSerializer,
	PaymentConfirmSerializer,
	PaymentIntentSerializer,
	PaymentSerializer,
	PlaceOrderSerializer,
	ReservationSerializer,
)
from leeaicore.sysutils.constants import ComplaintStatus, OrderStatus, PaymentStatus


class MenuListAPI(APIView):
	permission_classes = (permissions.AllowAny,)

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

	@extend_schema(request=PlaceOrderSerializer, responses={200: OrderSerializer}, operation_id='place_order')
	def post(self, request):
		ser = PlaceOrderSerializer(data=request.data, context={"request": request})
		ser.is_valid(raise_exception=True)
		order = ser.save()
		return Response(OrderSerializer(order).data, status=status.HTTP_200_OK)


class OrderStatusAPI(APIView):
	permission_classes = (permissions.IsAuthenticated,)

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

	@extend_schema(responses={200: ReservationSerializer(many=True)}, operation_id='list_reservations')
	def get(self, request):
		qs = Reservation.objects.filter(user=request.user).order_by("-created_at")
		return Response(ReservationSerializer(qs, many=True).data)

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

	@extend_schema(request=ComplaintSerializer, responses={200: ComplaintSerializer}, operation_id='submit_complaint')
	def post(self, request):
		data = {**request.data}
		ser = ComplaintSerializer(data=data)
		ser.is_valid(raise_exception=True)
		complaint = ser.save(user=request.user, status=ComplaintStatus.OPEN.value)
		return Response(ComplaintSerializer(complaint).data, status=200)


class PaymentIntentAPI(APIView):
	permission_classes = (permissions.IsAuthenticated,)

	@extend_schema(request=PaymentIntentSerializer, responses={200: PaymentSerializer}, operation_id='payment_intent')
	@transaction.atomic
	def post(self, request):
		ser = PaymentIntentSerializer(data=request.data)
		ser.is_valid(raise_exception=True)
		ord_id = ser.validated_data["ord_id"]
		provider = ser.validated_data.get("provider", "MOCK")

		order = Order.objects.filter(ord_id=ord_id, user=request.user).first()
		if not order:
			return Response({"message": "Order not found"}, status=404)
		if order.payment_status.lower() == "paid":
			return Response({"message": "Order already paid"}, status=400)

		payment = Payment.objects.create(
			order=order,
			user=request.user,
			amount=order.total_price,
			currency=order.currency,
			provider=provider,
			status=PaymentStatus.PENDING.value,
			client_secret=f"mock_{order.ord_id}_secret",
		)
		return Response(PaymentSerializer(payment).data)


class PaymentConfirmAPI(APIView):
	permission_classes = (permissions.IsAuthenticated,)

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

		txn_id = ser.validated_data["transaction_id"]
		# Mock verification success
		payment.transaction_id = txn_id
		payment.status = PaymentStatus.SUCCEEDED.value
		payment.save(update_fields=["transaction_id", "status", "updated_at"])

		order.payment_status = "Paid"
		order.status = OrderStatus.CONFIRMED.value
		order.save(update_fields=["payment_status", "status", "updated_at"])

		return Response(PaymentSerializer(payment).data, status=200)


class ChatbotIntentAPI(APIView):
	permission_classes = (permissions.AllowAny,)

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
