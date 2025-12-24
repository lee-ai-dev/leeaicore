from typing import List
from django.db import transaction
from rest_framework import serializers

from accounts.models import Restaurant, User, OperationalHours
from accounts.serializers import UserSerializer
from api.models import Complaint, Dish, Order, OrderItem, Payment, PaymentRefund, Reservation, Table, SubscriptionPackage, Subscription
from leeaicore.sysutils.constants import ComplaintStatus, OrderStatus, PaymentStatus



class RestaurantCreateSerializer(serializers.ModelSerializer):
    class Meta:
        model = Restaurant
        fields = (
            "name",
            "phone",
            "whatsapp",
            "instagram",
            "facebook",
            "twitter",
            "bank_account_number",
            "bank_name",
            "bank_code",
            "bank_branch",
            "website",
        )

    def create(self, validated_data):
        # Allow passing user via serializer.save(user=...), otherwise use request user.
        user = validated_data.pop("user", None) or self.context["request"].user
        # Ensure a user can only own one restaurant
        if Restaurant.objects.filter(user=user).exists():
            raise serializers.ValidationError("User already has a restaurant")
        restaurant = Restaurant.objects.create(user=user, **validated_data)
        # Optionally set role to RESTAURANT
        if getattr(user, "role", None) != "RESTAURANT":
            user.role = "RESTAURANT"
            user.save(update_fields=["role"])
        return restaurant


class RestaurantProfileSerializer(serializers.ModelSerializer):
    user = UserSerializer(read_only=True)

    class Meta:
        model = Restaurant
        fields = "__all__"

class DishSerializer(serializers.ModelSerializer):
    restaurant = RestaurantProfileSerializer(read_only=True)
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
        fields = ("id", "table", "restaurant", "user", "status", 'date', 'time', "created_at", "updated_at")
        read_only_fields = ("status", "user")

class ReadonlyReservationSerializer(serializers.ModelSerializer):
    table = TableSerializer(read_only=True)
    restaurant = RestaurantProfileSerializer(read_only=True)
    user = UserSerializer(read_only=True)
    user_name = serializers.CharField(source='user.name', read_only=True)

    class Meta:
        model = Reservation
        fields = ("id", "table", "restaurant", "user","user_name", "status", 'date', 'time', "created_at", "updated_at")
        read_only_fields = ("status", "user", "table", "restaurant")


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


class AccountDetailVerificationRequestSerializer(serializers.Serializer):
    account_number = serializers.CharField(max_length=50)
    bank_code = serializers.CharField(max_length=50)


class AccountDetailVerificationResponseSerializer(serializers.Serializer):
    provider = serializers.CharField()
    account_number = serializers.CharField(allow_blank=True, required=False)
    account_name = serializers.CharField(allow_blank=True, required=False)
    bank_code = serializers.CharField(allow_blank=True, required=False)
    bank_id = serializers.IntegerField(required=False)
    raw = serializers.DictField(child=serializers.JSONField(), required=False)


class PaymentSerializer(serializers.ModelSerializer):
    user_name = serializers.CharField(source='user.name', read_only=True)
    restaurant_name = serializers.CharField(source='order.restaurant.name', read_only=True)
    class Meta:
        model = Payment
        fields = "__all__"
        read_only_fields = ("status", "amount", "currency", "user", "user_name", "restaurant_name", "created_at")


class PaymentRefundSerializer(serializers.ModelSerializer):
    class Meta:
        model = PaymentRefund
        fields = ("id", "payment", "user", "initiated_by", "amount", "reason", "status", "provider_reference", "created_at")
        read_only_fields = ("initiated_by", "status", "provider_reference", "created_at")

    def validate(self, attrs):
        payment: Payment = attrs.get("payment")
        amount = attrs.get("amount")
        if payment is None:
            raise serializers.ValidationError("payment is required")
			
        if payment.status != PaymentStatus.SUCCEEDED.value:
            raise serializers.ValidationError("Only successful payments can be refunded")
			
        # Prevent refunding more than paid (consider existing refunds)
        total_refunded = PaymentRefund.objects.filter(payment=payment, status__in=["PENDING", "COMPLETED"]).aggregate(total=serializers.DecimalField(max_digits=12, decimal_places=2).to_internal_value("0"))
        # Simpler: sum in Python
        existing = sum(r.amount for r in PaymentRefund.objects.filter(payment=payment, status__in=["PENDING", "COMPLETED"]))
        if amount + existing > payment.amount:
            raise serializers.ValidationError("Refund amount exceeds original payment amount")
        return attrs


class SubscriptionPackageSerializer(serializers.ModelSerializer):
    class Meta:
        model = SubscriptionPackage
        fields = (
            "id",
            "name",
            "price",
            "currency",
            "max_dishes",
            "max_tables",
            "max_orders",
            "max_reservations",
            "created_at",
            "updated_at",
        )


class SubscriptionSerializer(serializers.ModelSerializer):
    package = SubscriptionPackageSerializer(read_only=True)
    package_id = serializers.PrimaryKeyRelatedField(
        queryset=SubscriptionPackage.objects.all(), write_only=True, source="package"
    )

    class Meta:
        model = Subscription
        fields = (
            "id",
            "restaurant",
            "package",
            "package_id",
            "status",
            "start_date",
            "end_date",
            "paystack_reference",
            "created_at",
            "updated_at",
        )
        read_only_fields = ("restaurant", "status", "start_date", "end_date", "paystack_reference")


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


class AdminRestaurantUserSerializer(serializers.ModelSerializer):
    status = serializers.SerializerMethodField()

    class Meta:
        model = User
        fields = ("id", "name", "email", "role", "status")

    def get_status(self, obj):
        return "active" if obj.is_active else "inactive"


class AdminRestaurantListSerializer(serializers.ModelSerializer):
    user_id = serializers.IntegerField(source='user.id', read_only=True)
    user_name = serializers.CharField(source='user.name', read_only=True)
    user_role = serializers.CharField(source='user.role', read_only=True)
    subscription_name = serializers.SerializerMethodField()
    subscription_status = serializers.SerializerMethodField()

    class Meta:
        model = Restaurant
        fields = (
            "id",
            "name",
            "rid",
            "phone",
            "whatsapp",
            "instagram",
            "facebook",
            "website",
            "is_suspended",
            "suspension_reason",
            "created_at",
            "updated_at",
            "user_id",
            "user_name",
            "user_role",
            "subscription_name",
            "subscription_status",
        )

    def get_subscription_name(self, obj):
        sub = obj.subscriptions.order_by('-created_at').first()
        return sub.package.name if sub and sub.package else None

    def get_subscription_status(self, obj):
        sub = obj.subscriptions.order_by('-created_at').first()
        return sub.status if sub else None


class BankSerializer(serializers.Serializer):
    """Shape of a single bank item as returned by Paystack /bank."""

    name = serializers.CharField()
    slug = serializers.CharField(required=False, allow_blank=True)
    code = serializers.CharField(required=False, allow_blank=True)
    longcode = serializers.CharField(required=False, allow_blank=True, allow_null=True)
    gateway = serializers.CharField(required=False, allow_blank=True, allow_null=True)
    pay_with_bank = serializers.BooleanField(required=False)
    active = serializers.BooleanField(required=False)
    country = serializers.CharField(required=False, allow_blank=True)
    currency = serializers.CharField(required=False, allow_blank=True)
    type = serializers.CharField(required=False, allow_blank=True)


class BanksListResponseSerializer(serializers.Serializer):
    provider = serializers.CharField()
    banks = BankSerializer(many=True)

class IntegrationSummarySerializer(serializers.Serializer):
	integration = serializers.CharField()
	clients = serializers.IntegerField()
	category = serializers.CharField()
	status = serializers.CharField()
	lastsync = serializers.DateTimeField()

class IntegrationsSummaryOverviewSerializer(serializers.Serializer):
	total_clients = serializers.IntegerField()
	supported_integrations = serializers.IntegerField()
	failed_integrations = serializers.IntegerField()
	most_used_integration = serializers.CharField(allow_null=True)


class IntegrationsSummaryDataSerializer(serializers.Serializer):
    summary = IntegrationsSummaryOverviewSerializer()
    data = IntegrationSummarySerializer(many=True)