from django.contrib import admin
from api.models import Dish, Order, OrderItem, Table, Reservation, Payment, Complaint

@admin.register(Dish)
class DishAdmin(admin.ModelAdmin):
	list_display = ("id", "name", "restaurant", "price", "in_stock", "availability", "updated_at")
	list_filter = ("restaurant", "in_stock", "availability")
	search_fields = ("name", "description")

@admin.register(OrderItem)
class OrderItemAdmin(admin.ModelAdmin):
	list_display = ("id", "dish", "quantity", "created_at")

@admin.register(Order)
class OrderAdmin(admin.ModelAdmin):
	list_display = ("id", "ord_id", "user", "restaurant", "total_price", "status", "payment_status", "created_at")
	search_fields = ("ord_id", "user__email", "user__name")
	list_filter = ("status", "payment_status", "restaurant")
	date_hierarchy = "created_at"

@admin.register(Table)
class TableAdmin(admin.ModelAdmin):
	list_display = ("id", "table_id", "capacity", "price", "available", "updated_at")
	list_filter = ("available", "capacity")

@admin.register(Reservation)
class ReservationAdmin(admin.ModelAdmin):
	list_display = ("id", "table", "restaurant", "user", "status", "created_at")
	list_filter = ("status", "restaurant")

@admin.register(Payment)
class PaymentAdmin(admin.ModelAdmin):
	list_display = ("id", "order", "user", "amount", "currency", "provider", "status", "transaction_id", "created_at")
	list_filter = ("provider", "status")
	search_fields = ("order__ord_id", "transaction_id")

@admin.register(Complaint)
class ComplaintAdmin(admin.ModelAdmin):
	list_display = ("id", "user", "restaurant", "order", "subject", "status", "created_at")
	list_filter = ("status",)
	search_fields = ("subject", "message")
