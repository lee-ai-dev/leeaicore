import json

from django.conf import settings
from django.utils import timezone
from rest_framework import permissions, status
from rest_framework.response import Response
from rest_framework.views import APIView
from drf_spectacular.utils import extend_schema, OpenApiParameter
from drf_spectacular.types import OpenApiTypes

from accounts.models import Restaurant
from leeaicore.sysutils.permissions import IsStaffAdmin

from .models import WhatsAppInboundMessage, WhatsAppIntegration, WhatsAppOutboundMessage
from .serializers import AdminWhatsAppIntegrationUpsertSerializer, WhatsAppIntegrationSerializer
from .services import WhatsAppCloudClient, build_integrations_summary, extract_message_events, verify_whatsapp_signature
from .whatsapp_bot import get_or_create_contact, handle_inbound_text


class WhatsAppWebhookAPIView(APIView):
	"""Meta WhatsApp Cloud API webhook endpoint.

	- GET: verification handshake
	- POST: inbound messages/statuses
	"""
	permission_classes = (permissions.AllowAny,)

	@extend_schema(
		parameters=[
			OpenApiParameter(name='hub.mode', type=OpenApiTypes.STR, location=OpenApiParameter.QUERY, required=False),
			OpenApiParameter(name='hub.verify_token', type=OpenApiTypes.STR, location=OpenApiParameter.QUERY, required=False),
			OpenApiParameter(name='hub.challenge', type=OpenApiTypes.STR, location=OpenApiParameter.QUERY, required=False),
		],
		responses={200: dict},
		operation_id='whatsapp_webhook_verify',
	)
	def get(self, request):
		mode = request.query_params.get('hub.mode')
		token = request.query_params.get('hub.verify_token')
		challenge = request.query_params.get('hub.challenge')

		expected = getattr(settings, 'WHATSAPP_WEBHOOK_VERIFY_TOKEN', '')
		if mode == 'subscribe' and expected and token == expected and challenge is not None:
			return Response(challenge, status=200)
		return Response({'message': 'Invalid verify token'}, status=403)

	@extend_schema(
		request=None,
		responses={200: dict},
		operation_id='whatsapp_webhook_ingest',
	)
	def post(self, request):
		# Validate signature if configured
		app_secret = getattr(settings, 'WHATSAPP_APP_SECRET', '')
		validate = getattr(settings, 'WHATSAPP_VALIDATE_SIGNATURE', True)
		sig = request.headers.get('X-Hub-Signature-256') or request.META.get('HTTP_X_HUB_SIGNATURE_256')
		body = request.body or b''
		if validate and app_secret:
			if not verify_whatsapp_signature(app_secret=app_secret, body=body, signature_header=sig):
				return Response({'message': 'Invalid signature'}, status=403)

		payload = request.data if isinstance(request.data, dict) else {}
		events = extract_message_events(payload)
		# Always ack quickly; process inline for now
		for ev in events:
			integration = WhatsAppIntegration.objects.filter(phone_number_id=ev.phone_number_id).select_related('restaurant').first()
			if not integration or not integration.enabled:
				continue

			# idempotency
			if WhatsAppInboundMessage.objects.filter(message_id=ev.message_id).exists():
				continue

			contact = get_or_create_contact(integration, wa_id=ev.wa_id)
			inbound = WhatsAppInboundMessage.objects.create(
				integration=integration,
				contact=contact,
				message_id=ev.message_id,
				from_wa_id=ev.wa_id,
				message_type=ev.message_type,
				text=ev.text,
				raw=ev.raw,
			)

			integration.last_inbound_at = timezone.now()
			integration.save(update_fields=['last_inbound_at', 'updated_at'])

			try:
				replies = handle_inbound_text(integration=integration, contact=contact, text=ev.text)
				for msg in replies:
					self._send_reply(integration=integration, to_wa_id=contact.wa_id, reply=msg, contact_id=contact.id)
				inbound.processed = True
				inbound.save(update_fields=['processed', 'updated_at'])
			except Exception as e:
				inbound.error = str(e)
				inbound.save(update_fields=['error', 'updated_at'])
				integration.last_error = str(e)
				integration.save(update_fields=['last_error', 'updated_at'])

		return Response({'status': 'ok'}, status=200)

	def _send_reply(self, *, integration: WhatsAppIntegration, to_wa_id: str, reply, contact_id: int | None):
		send = getattr(settings, 'WHATSAPP_SEND_MESSAGES', False)
		client = WhatsAppCloudClient(access_token=(integration.access_token or None))

		kind = 'text'
		text = ''
		payload = {}
		if isinstance(reply, dict):
			kind = (reply.get('kind') or 'text')
			if kind == 'text':
				text = str(reply.get('text') or '')
				payload = {'type': 'text', 'text': {'body': text}}
			elif kind == 'buttons':
				text = str(reply.get('body') or '')
				payload = reply
			elif kind == 'list':
				text = str(reply.get('body') or '')
				payload = reply
			else:
				kind = 'text'
				text = str(reply.get('text') or reply.get('body') or '')
				payload = {'type': 'text', 'text': {'body': text}}
		else:
			text = str(reply or '')
			payload = {'type': 'text', 'text': {'body': text}}

		out = WhatsAppOutboundMessage.objects.create(
			integration=integration,
			contact_id=contact_id,
			to_wa_id=to_wa_id,
			message_type=kind,
			text=text,
			raw=payload,
			sent_ok=False,
		)
		if not send:
			out.sent_ok = True
			out.raw = {'skipped_send': True, 'payload': payload}
			out.save(update_fields=['sent_ok', 'raw', 'updated_at'])
			return

		try:
			if kind == 'text':
				resp = client.send_text(phone_number_id=integration.phone_number_id, to=to_wa_id, text=text)
			elif kind == 'buttons':
				resp = client.send_buttons(
					phone_number_id=integration.phone_number_id,
					to=to_wa_id,
					body=str(payload.get('body') or ''),
					buttons=list(payload.get('buttons') or []),
				)
			elif kind == 'list':
				resp = client.send_list(
					phone_number_id=integration.phone_number_id,
					to=to_wa_id,
					body=str(payload.get('body') or ''),
					button_text=str(payload.get('button_text') or 'Choose'),
					sections=list(payload.get('sections') or []),
				)
			else:
				resp = client.send_text(phone_number_id=integration.phone_number_id, to=to_wa_id, text=text)

			msgs = resp.get('messages') or []
			out.provider_message_id = (msgs[0].get('id') if msgs else None)
			out.raw = resp
			out.sent_ok = True
			out.save(update_fields=['provider_message_id', 'raw', 'sent_ok', 'updated_at'])
			integration.last_outbound_at = timezone.now()
			integration.save(update_fields=['last_outbound_at', 'updated_at'])
		except Exception as e:
			out.error = str(e)
			out.sent_ok = False
			out.save(update_fields=['error', 'sent_ok', 'updated_at'])
			integration.last_error = str(e)
			integration.save(update_fields=['last_error', 'updated_at'])


class RestaurantWhatsAppIntegrationAPIView(APIView):
	"""Restaurant owner: view/update their WhatsApp integration config."""
	permission_classes = (permissions.IsAuthenticated,)
	throttle_scope = 'restaurant'

	@extend_schema(responses={200: WhatsAppIntegrationSerializer}, operation_id='restaurant_whatsapp_integration_get')
	def get(self, request):
		restaurant = Restaurant.objects.filter(user=request.user).first()
		if not restaurant and not (request.user.is_staff or request.user.is_superuser):
			return Response({'message': 'Restaurant profile not found'}, status=404)
		if restaurant:
			obj = WhatsAppIntegration.objects.filter(restaurant=restaurant).first()
			if not obj:
				return Response({'message': 'WhatsApp integration not configured'}, status=404)
			return Response(WhatsAppIntegrationSerializer(obj).data)

		# Staff fallback: allow listing none
		return Response({'message': 'Restaurant not resolved for this user'}, status=400)

	@extend_schema(request=WhatsAppIntegrationSerializer, responses={200: WhatsAppIntegrationSerializer}, operation_id='restaurant_whatsapp_integration_upsert')
	def post(self, request):
		restaurant = Restaurant.objects.filter(user=request.user).first()
		if not restaurant and not (request.user.is_staff or request.user.is_superuser):
			return Response({'message': 'Restaurant profile not found'}, status=404)
		if not restaurant:
			return Response({'message': 'Restaurant not resolved for this user'}, status=400)

		obj = WhatsAppIntegration.objects.filter(restaurant=restaurant).first()
		ser = WhatsAppIntegrationSerializer(instance=obj, data=request.data, partial=True)
		ser.is_valid(raise_exception=True)
		integration = ser.save(restaurant=restaurant)
		return Response(WhatsAppIntegrationSerializer(integration).data, status=200)


class RestaurantWhatsAppIntegrationHealthAPIView(APIView):
	"""Restaurant owner: validate that phone_number_id + token can reach Meta Graph API."""
	permission_classes = (permissions.IsAuthenticated,)
	throttle_scope = 'restaurant'

	@extend_schema(
		responses={200: dict},
		operation_id='restaurant_whatsapp_integration_health',
		description='Checks the configured WhatsApp integration against Meta Graph API.',
	)
	def get(self, request):
		restaurant = Restaurant.objects.filter(user=request.user).first()
		if not restaurant and not (request.user.is_staff or request.user.is_superuser):
			return Response({'message': 'Restaurant profile not found'}, status=404)
		if not restaurant:
			return Response({'message': 'Restaurant not resolved for this user'}, status=400)

		integration = WhatsAppIntegration.objects.filter(restaurant=restaurant).first()
		if not integration:
			return Response({'message': 'WhatsApp integration not configured'}, status=404)
		if not integration.phone_number_id:
			return Response({'message': 'phone_number_id not configured'}, status=400)

		client = WhatsAppCloudClient(access_token=(integration.access_token or None))
		try:
			details = client.get_phone_number_details(phone_number_id=integration.phone_number_id)
		except Exception as e:
			return Response(
				{
					'ok': False,
					'phone_number_id': integration.phone_number_id,
					'error': str(e),
				},
				status=400,
			)

		return Response(
			{
				'ok': True,
				'phone_number_id': integration.phone_number_id,
				'details': details,
			},
			status=200,
		)


class AdminIntegrationsSummaryAPIView(APIView):
	"""Admin summary of integrations (real data)."""
	permission_classes = (IsStaffAdmin,)
	throttle_scope = 'admin'

	@extend_schema(
		responses={200: dict},
		operation_id='admin_integrations_summary',
		description='Admin-only integrations summary (computed).'
	)
	def get(self, request):
		return Response(build_integrations_summary(), status=200)


class AdminWhatsAppIntegrationsAPIView(APIView):
	"""Admin onboarding: CRUD WhatsApp integrations per restaurant."""
	permission_classes = (IsStaffAdmin,)
	throttle_scope = 'admin'

	@extend_schema(responses={200: WhatsAppIntegrationSerializer(many=True)}, operation_id='admin_whatsapp_integrations_list')
	def get(self, request):
		qs = WhatsAppIntegration.objects.select_related('restaurant').all().order_by('-updated_at')
		return Response(WhatsAppIntegrationSerializer(qs, many=True).data)

	@extend_schema(request=AdminWhatsAppIntegrationUpsertSerializer, responses={201: WhatsAppIntegrationSerializer}, operation_id='admin_whatsapp_integrations_create')
	def post(self, request):
		ser = AdminWhatsAppIntegrationUpsertSerializer(data=request.data)
		ser.is_valid(raise_exception=True)
		restaurant_id = ser.validated_data.pop('restaurant_id')
		restaurant = Restaurant.objects.filter(id=restaurant_id).first()
		if not restaurant:
			return Response({'message': 'Restaurant not found'}, status=404)
		obj = WhatsAppIntegration.objects.create(restaurant=restaurant, **ser.validated_data)
		return Response(WhatsAppIntegrationSerializer(obj).data, status=201)


class AdminWhatsAppIntegrationDetailAPIView(APIView):
	permission_classes = (IsStaffAdmin,)
	throttle_scope = 'admin'

	@extend_schema(responses={200: WhatsAppIntegrationSerializer}, operation_id='admin_whatsapp_integrations_get')
	def get(self, request, pk: int):
		obj = WhatsAppIntegration.objects.select_related('restaurant').filter(id=pk).first()
		if not obj:
			return Response({'message': 'Not found'}, status=404)
		return Response(WhatsAppIntegrationSerializer(obj).data)

	@extend_schema(request=AdminWhatsAppIntegrationUpsertSerializer, responses={200: WhatsAppIntegrationSerializer}, operation_id='admin_whatsapp_integrations_update')
	def patch(self, request, pk: int):
		obj = WhatsAppIntegration.objects.select_related('restaurant').filter(id=pk).first()
		if not obj:
			return Response({'message': 'Not found'}, status=404)
		ser = AdminWhatsAppIntegrationUpsertSerializer(instance=obj, data=request.data, partial=True)
		ser.is_valid(raise_exception=True)
		# restaurant_id is optional; if provided, reassign
		restaurant_id = ser.validated_data.pop('restaurant_id', None)
		if restaurant_id is not None:
			restaurant = Restaurant.objects.filter(id=restaurant_id).first()
			if not restaurant:
				return Response({'message': 'Restaurant not found'}, status=404)
			obj.restaurant = restaurant
		obj = ser.save()
		return Response(WhatsAppIntegrationSerializer(obj).data)

	@extend_schema(responses={204: None}, operation_id='admin_whatsapp_integrations_delete')
	def delete(self, request, pk: int):
		obj = WhatsAppIntegration.objects.filter(id=pk).first()
		if not obj:
			return Response({'message': 'Not found'}, status=404)
		obj.delete()
		return Response(status=204)
