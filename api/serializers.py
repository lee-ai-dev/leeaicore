from typing import List
from django.db import transaction
from rest_framework import serializers

from accounts.models import Restaurant, User, OperationalHours
from api.models import Complaint, Dish, Order, OrderItem, Payment, Reservation, Table
from leeaicore.sysutils.constants import ComplaintStatus, OrderStatus, PaymentStatus


class DishSerializer(serializers.ModelSerializer):
    class Meta:
        model = Dish
        fields = "__all__"


class DishCreateUpdateSerializer(serializers.ModelSerializer):
    class Meta:
        model = Dish
        exclude = ("restaurant", "created_at", "updated_at")


class MenuQuerySerializer(serializers.Serializer):
    restaurant_rid = serializers.CharField(required=False, allow_blank=True)
    q = serializers.CharField(required=False, allow_blank=True)


class OrderItemInputSerializer(serializers.Serializer):
    dish_id = serializers.IntegerField()
    quantity = serializers.IntegerField(min_value=1, default=1)


class OrderItemSerializer(serializers.ModelSerializer):
    dish = DishSerializer()
    class Meta:
        model = OrderItem
        fields = ("id", "dish", "quantity")


class OrderSerializer(serializers.ModelSerializer):
    items = OrderItemSerializer(many=True)
    class Meta:
        model = Order
        fields = (
            "id", "ord_id", "user", "restaurant", "items", "total_price", "status",
            "delivery_address", "payment_method", "payment_status", "currency",
            "special_instructions", "created_at", "updated_at"
        )
        read_only_fields = ("ord_id", "total_price", "status", "payment_status")


class PlaceOrderSerializer(serializers.Serializer):
    restaurant_rid = serializers.CharField()
    items = OrderItemInputSerializer(many=True)
    delivery_address = serializers.CharField()
    payment_method = serializers.CharField(required=False, default="Cash on Delivery")
    special_instructions = serializers.CharField(required=False, allow_blank=True, allow_null=True)

    def validate(self, attrs):
        rid = attrs.get("restaurant_rid")
        items: List[dict] = attrs.get("items", [])
        if not Restaurant.objects.filter(rid=rid).exists():
            raise serializers.ValidationError("Invalid restaurant_rid")
        if not items:
            raise serializers.ValidationError("At least one item is required")
        dish_ids = [i["dish_id"] for i in items]
        found = set(Dish.objects.filter(id__in=dish_ids, in_stock=True).values_list("id", flat=True))
        missing = [d for d in dish_ids if d not in found]
        if missing:
            raise serializers.ValidationError(f"One or more dishes not found or out of stock: {missing}")
        return attrs

    @transaction.atomic
    def create(self, validated_data):
        user: User = self.context["request"].user
        restaurant = Restaurant.objects.get(rid=validated_data["restaurant_rid"])
        order = Order.objects.create(
            user=user,
            restaurant=restaurant,
            delivery_address=validated_data["delivery_address"],
            payment_method=validated_data.get("payment_method", "Cash on Delivery"),
            special_instructions=validated_data.get("special_instructions"),
            status=OrderStatus.PENDING.value,
            payment_status="Unpaid",
        )
        item_objs = []
        for it in validated_data["items"]:
            dish = Dish.objects.get(id=it["dish_id"])
            item_objs.append(OrderItem.objects.create(dish=dish, quantity=it["quantity"]))
        order.items.add(*item_objs)

        # Ensure total price correct via aggregation
        total = sum(io.dish.price * io.quantity for io in item_objs)
        Order.objects.filter(pk=order.pk).update(total_price=total)
        order.refresh_from_db()
        return order


class OrderStatusQuerySerializer(serializers.Serializer):
    ord_id = serializers.CharField()


class TableSerializer(serializers.ModelSerializer):
    class Meta:
        model = Table
        fields = "__all__"


class TableCreateUpdateSerializer(serializers.ModelSerializer):
    class Meta:
        model = Table
        exclude = ("created_at", "updated_at")


class ReservationSerializer(serializers.ModelSerializer):
    class Meta:
        model = Reservation
        fields = ("id", "table", "restaurant", "user", "status", "created_at", "updated_at")
        read_only_fields = ("status", "user")


class ComplaintSerializer(serializers.ModelSerializer):
    class Meta:
        model = Complaint
        fields = ("id", "user", "restaurant", "order", "subject", "message", "status", "created_at", "updated_at")
        read_only_fields = ("user", "status")


class PaymentIntentSerializer(serializers.Serializer):
    ord_id = serializers.CharField()
    provider = serializers.CharField(required=False, default="MOCK")


class PaymentConfirmSerializer(serializers.Serializer):
    ord_id = serializers.CharField()
    transaction_id = serializers.CharField(required=False, allow_blank=True)
    reference = serializers.CharField(required=False, allow_blank=True)


class PaymentSerializer(serializers.ModelSerializer):
    class Meta:
        model = Payment
        fields = "__all__"
        read_only_fields = ("status", "amount", "currency", "user")


class OrderStatusUpdateSerializer(serializers.Serializer):
    status = serializers.ChoiceField(choices=[(s.value, s.value) for s in OrderStatus])


class ReservationStatusUpdateSerializer(serializers.Serializer):
    status = serializers.ChoiceField(choices=[("APPROVED", "APPROVED"), ("PENDING", "PENDING"), ("CANCELLED", "CANCELLED")])


class OperationalHoursSerializer(serializers.ModelSerializer):
    class Meta:
        model = OperationalHours
        fields = "__all__"


class OperationalHoursCreateUpdateSerializer(serializers.ModelSerializer):
    class Meta:
        model = OperationalHours
        exclude = ("restaurant", "created_at", "updated_at")

    def validate(self, attrs):
        open_time = attrs.get('open_time')
        close_time = attrs.get('close_time')
        if open_time and close_time and close_time <= open_time:
            raise serializers.ValidationError("close_time must be after open_time")
        return attrs


class OperationalHoursDaySerializer(serializers.Serializer):
    day_of_week = serializers.ChoiceField(choices=[d for d, _ in OperationalHours.DAYS_OF_WEEK])
    open_time = serializers.TimeField(required=False)
    close_time = serializers.TimeField(required=False)
    closed = serializers.BooleanField(required=False, default=False)

    def validate(self, attrs):
        closed = attrs.get('closed', False)
        if not closed:
            if not attrs.get('open_time') or not attrs.get('close_time'):
                raise serializers.ValidationError("open_time and close_time are required when not closed")
            if attrs['close_time'] <= attrs['open_time']:
                raise serializers.ValidationError("close_time must be after open_time")
        return attrs


class OperationalHoursBatchUpsertSerializer(serializers.Serializer):
    days = OperationalHoursDaySerializer(many=True)
