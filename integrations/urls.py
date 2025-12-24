from django.urls import path

from .views import (
    AdminIntegrationsSummaryAPIView,
    AdminWhatsAppIntegrationDetailAPIView,
    AdminWhatsAppIntegrationsAPIView,
    RestaurantWhatsAppIntegrationHealthAPIView,
    RestaurantWhatsAppIntegrationAPIView,
    WhatsAppWebhookAPIView,
)

urlpatterns = [
    # Meta webhook
    path('whatsapp/webhook/', WhatsAppWebhookAPIView.as_view(), name='whatsapp_webhook'),

    # Restaurant config
    path('whatsapp/me/', RestaurantWhatsAppIntegrationAPIView.as_view(), name='whatsapp_integration_me'),
	path('whatsapp/health/', RestaurantWhatsAppIntegrationHealthAPIView.as_view(), name='whatsapp_integration_health'),

	# Admin onboarding + summary
	path('admin/summary/', AdminIntegrationsSummaryAPIView.as_view(), name='admin_integrations_summary'),
	path('admin/whatsapp/', AdminWhatsAppIntegrationsAPIView.as_view(), name='admin_whatsapp_integrations'),
	path('admin/whatsapp/<int:pk>/', AdminWhatsAppIntegrationDetailAPIView.as_view(), name='admin_whatsapp_integration_detail'),
]
