from django.contrib import admin
from accounts.models import User, Restaurant, Wallet, FCMDevice, OTP

@admin.register(User)
class UserAdmin(admin.ModelAdmin):
	list_display = ("id", "email", "phone", "name", "is_active", "is_staff", "admin_verified", "created_at")
	search_fields = ("email", "phone", "name")
	list_filter = ("is_active", "is_staff", "is_superuser", "admin_verified")
	readonly_fields = ("last_login", "created_at", "updated_at")

@admin.register(Restaurant)
class RestaurantAdmin(admin.ModelAdmin):
	list_display = ("id", "rid", "name", "phone", "user", "created_at")
	search_fields = ("rid", "name", "phone")

@admin.register(Wallet)
class WalletAdmin(admin.ModelAdmin):
	list_display = ("id", "restaurant", "balance", "updated_at")

@admin.register(FCMDevice)
class FCMDeviceAdmin(admin.ModelAdmin):
	list_display = ("id", "user", "token", "created_at")
	search_fields = ("token", "user__email", "user__name")

@admin.register(OTP)
class OTPAdmin(admin.ModelAdmin):
	list_display = ("id", "phone", "otp", "created_at")
	search_fields = ("phone",)
