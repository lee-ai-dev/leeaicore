from django.apps import apps as django_apps
from django.contrib import admin
from django.contrib.admin.sites import AlreadyRegistered

from accounts.models import User, Restaurant, Wallet, FCMDevice, OTP, OperationalHours

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

@admin.register(OperationalHours)
class OperationalHoursAdmin(admin.ModelAdmin):
	list_display = ("id", "restaurant", "day_of_week", "open_time", "close_time", "created_at")
	list_filter = ("day_of_week", "restaurant")
	search_fields = ("restaurant__name", "restaurant__rid")


def _register_all_models(app_label: str) -> None:
	for model in django_apps.get_app_config(app_label).get_models():
		try:
			admin.site.register(model)
		except AlreadyRegistered:
			pass


_register_all_models('accounts')
