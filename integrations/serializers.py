from rest_framework import serializers

from .models import WhatsAppIntegration


class WhatsAppIntegrationSerializer(serializers.ModelSerializer):
    restaurant_id = serializers.IntegerField(source='restaurant.id', read_only=True)

    class Meta:
        model = WhatsAppIntegration
        fields = (
            'id',
            'restaurant_id',
            'enabled',
            'display_name',
            'phone_number_id',
            'waba_id',
            'business_account_id',
            'access_token',
            'last_inbound_at',
            'last_outbound_at',
            'last_error',
            'created_at',
            'updated_at',
        )
        read_only_fields = ('last_inbound_at', 'last_outbound_at', 'last_error', 'created_at', 'updated_at')


class AdminWhatsAppIntegrationUpsertSerializer(serializers.ModelSerializer):
    restaurant_id = serializers.IntegerField(write_only=True)

    class Meta:
        model = WhatsAppIntegration
        fields = (
            'id',
            'restaurant_id',
            'enabled',
            'display_name',
            'phone_number_id',
            'waba_id',
            'business_account_id',
            'access_token',
        )

