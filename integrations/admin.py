from django.apps import apps as django_apps
from django.contrib import admin
from django.contrib.admin.sites import AlreadyRegistered

from .models import (
	WhatsAppContact,
	WhatsAppInboundMessage,
	WhatsAppIntegration,
	WhatsAppOutboundMessage,
	WhatsAppSession,
)


@admin.register(WhatsAppIntegration)
class WhatsAppIntegrationAdmin(admin.ModelAdmin):
	list_display = ('id', 'restaurant', 'enabled', 'phone_number_id', 'display_name', 'last_inbound_at', 'last_outbound_at')
	search_fields = ('phone_number_id', 'display_name', 'restaurant__name')
	list_filter = ('enabled',)


@admin.register(WhatsAppContact)
class WhatsAppContactAdmin(admin.ModelAdmin):
	list_display = ('id', 'integration', 'wa_id', 'name', 'user', 'created_at')
	search_fields = ('wa_id', 'name')


@admin.register(WhatsAppSession)
class WhatsAppSessionAdmin(admin.ModelAdmin):
	list_display = ('id', 'integration', 'contact', 'state', 'is_open', 'updated_at')
	list_filter = ('state', 'is_open')


@admin.register(WhatsAppInboundMessage)
class WhatsAppInboundMessageAdmin(admin.ModelAdmin):
	list_display = ('id', 'integration', 'from_wa_id', 'message_type', 'processed', 'created_at')
	search_fields = ('message_id', 'from_wa_id', 'text')
	list_filter = ('processed', 'message_type')


@admin.register(WhatsAppOutboundMessage)
class WhatsAppOutboundMessageAdmin(admin.ModelAdmin):
	list_display = ('id', 'integration', 'to_wa_id', 'message_type', 'sent_ok', 'created_at')
	search_fields = ('to_wa_id', 'text', 'provider_message_id')
	list_filter = ('sent_ok', 'message_type')


def _register_all_models(app_label: str) -> None:
	for model in django_apps.get_app_config(app_label).get_models():
		try:
			admin.site.register(model)
		except AlreadyRegistered:
			pass


_register_all_models('integrations')
