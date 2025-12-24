from django.test import TestCase, override_settings
from rest_framework.test import APIClient
from django.urls import reverse
from unittest.mock import patch

from accounts.models import Restaurant, User
from api.models import Dish, Order, Subscription, SubscriptionPackage

from .models import WhatsAppIntegration
from .services import extract_message_events


class WhatsAppIntegrationTests(TestCase):
	def setUp(self):
		self.client = APIClient()
		self.admin = User.objects.create_superuser(
			email='admin@example.com',
			phone='233200000010',
			password='pass1234',
			name='Admin',
		)
		self.owner = User.objects.create_user(
			email='owner@example.com',
			phone='233200000001',
			password='pass1234',
			name='Owner',
		)
		self.owner.role = 'RESTAURANT'
		self.owner.save(update_fields=['role'])
		self.restaurant = Restaurant.objects.create(user=self.owner, name='Test Resto', phone='0550000000')

		pkg = SubscriptionPackage.objects.create(
			name='Test Plan',
			price=0,
			currency='GHC',
			max_dishes=100,
			max_tables=100,
			max_orders=100,
			max_reservations=100,
		)
		Subscription.objects.create(restaurant=self.restaurant, package=pkg, status='ACTIVE')

		Dish.objects.create(
			restaurant=self.restaurant,
			name='Jollof',
			description='Rice',
			currency='GHC',
			in_stock=True,
			price=10,
			type='MAIN',
			tag='ghanaian',
		)

		self.integration = WhatsAppIntegration.objects.create(
			restaurant=self.restaurant,
			enabled=True,
			display_name='Test Bot',
			phone_number_id='1234567890',
		)

	def test_restaurant_can_upsert_whatsapp_integration(self):
		self.client.force_authenticate(user=self.owner)
		url = reverse('whatsapp_integration_me')
		res = self.client.post(url, {'enabled': True, 'display_name': 'My Bot', 'phone_number_id': '1234567890'}, format='json')
		self.assertEqual(res.status_code, 200, res.data)
		self.assertEqual(res.data['display_name'], 'My Bot')

	def test_admin_can_create_whatsapp_integration_for_restaurant(self):
		self.client.force_authenticate(user=self.admin)
		other_owner = User.objects.create_user(
			email='owner2@example.com',
			phone='233200000002',
			password='pass1234',
			name='Owner 2',
		)
		other_owner.role = 'RESTAURANT'
		other_owner.save(update_fields=['role'])
		other_restaurant = Restaurant.objects.create(user=other_owner, name='Test Resto 2', phone='0550000001')
		url = reverse('admin_whatsapp_integrations')
		res = self.client.post(url, {
			'restaurant_id': other_restaurant.id,
			'enabled': True,
			'display_name': 'Admin Bot',
			'phone_number_id': '999888777',
		}, format='json')
		self.assertEqual(res.status_code, 201, res.data)
		self.assertEqual(res.data['phone_number_id'], '999888777')

	def test_admin_integrations_summary_endpoint(self):
		self.client.force_authenticate(user=self.admin)
		url = reverse('admin_integrations_summary')
		res = self.client.get(url)
		self.assertEqual(res.status_code, 200, res.data)
		self.assertIn('summary', res.data)
		self.assertIn('data', res.data)
		# WhatsApp should be at least 1 because setUp creates one integration
		whatsapp_row = next((x for x in res.data['data'] if x.get('integration') == 'whatsapp'), None)
		self.assertIsNotNone(whatsapp_row)
		self.assertGreaterEqual(int(whatsapp_row.get('clients') or 0), 1)

	def test_api_admin_integrations_endpoint_uses_real_summary(self):
		self.client.force_authenticate(user=self.admin)
		res = self.client.get('/api-v1/integrations/')
		self.assertEqual(res.status_code, 200)
		whatsapp_row = next((x for x in res.data['data'] if x.get('integration') == 'whatsapp'), None)
		self.assertIsNotNone(whatsapp_row)

	@override_settings(WHATSAPP_WEBHOOK_VERIFY_TOKEN='verify_me')
	def test_webhook_verification(self):
		url = reverse('whatsapp_webhook')
		res = self.client.get(url, {
			'hub.mode': 'subscribe',
			'hub.verify_token': 'verify_me',
			'hub.challenge': '1234',
		})
		self.assertEqual(res.status_code, 200)
		self.assertEqual(res.data, '1234')

	@override_settings(WHATSAPP_SEND_MESSAGES=False, WHATSAPP_APP_SECRET='')
	def test_webhook_order_flow_creates_order(self):
		url = reverse('whatsapp_webhook')
		wa_id = '233200000099'

		# 1) user says "Order"
		payload1 = {
			'entry': [
				{'changes': [
					{'value': {
						'metadata': {'phone_number_id': '1234567890'},
						'messages': [{'from': wa_id, 'id': 'wamid.1', 'type': 'text', 'text': {'body': 'Order'}}],
					}}]
				}
			]
		}
		res1 = self.client.post(url, payload1, format='json')
		self.assertEqual(res1.status_code, 200)

		# 2) pick first item with qty 2
		payload2 = {
			'entry': [
				{'changes': [
					{'value': {
						'metadata': {'phone_number_id': '1234567890'},
						'messages': [{'from': wa_id, 'id': 'wamid.2', 'type': 'text', 'text': {'body': '1x2'}}],
					}}]
				}
			]
		}
		res2 = self.client.post(url, payload2, format='json')
		self.assertEqual(res2.status_code, 200)

		# 3) address
		payload3 = {
			'entry': [
				{'changes': [
					{'value': {
						'metadata': {'phone_number_id': '1234567890'},
						'messages': [{'from': wa_id, 'id': 'wamid.3', 'type': 'text', 'text': {'body': '123 Street'}}],
					}}]
				}
			]
		}
		res3 = self.client.post(url, payload3, format='json')
		self.assertEqual(res3.status_code, 200)

		self.assertTrue(Order.objects.filter(restaurant=self.restaurant).exists())
		order = Order.objects.filter(restaurant=self.restaurant).order_by('-created_at').first()
		self.assertEqual(order.delivery_address, '123 Street')
		self.assertEqual(order.total_price, 20)

	@override_settings(WHATSAPP_ACCESS_TOKEN='test_token', WHATSAPP_APP_SECRET='')
	@patch('integrations.services.requests.get')
	def test_restaurant_whatsapp_health_endpoint_ok(self, mock_get):
		mock_get.return_value.status_code = 200
		mock_get.return_value.content = b'{}'
		mock_get.return_value.json.return_value = {
			'id': self.integration.phone_number_id,
			'display_phone_number': '+233000000000',
			'verified_name': 'Test',
		}

		self.client.force_authenticate(user=self.owner)
		url = reverse('whatsapp_integration_health')
		res = self.client.get(url)
		self.assertEqual(res.status_code, 200, res.data)
		self.assertTrue(res.data.get('ok'))
		self.assertEqual(res.data.get('phone_number_id'), self.integration.phone_number_id)
		self.assertIn('details', res.data)
		mock_get.assert_called()

	def test_extract_message_events_prefers_interactive_reply_id(self):
		payload = {
			'entry': [
				{'changes': [
					{'value': {
						'metadata': {'phone_number_id': '1234567890'},
						'messages': [
							{
								'from': '233200000099',
								'id': 'wamid.99',
								'type': 'interactive',
								'interactive': {
									'type': 'list_reply',
									'list_reply': {'id': 'ORDER', 'title': 'Order'},
								},
							}
						]
					}}]
				}
			]
		}
		events = extract_message_events(payload)
		self.assertEqual(len(events), 1)
		self.assertEqual(events[0].text, 'ORDER')
