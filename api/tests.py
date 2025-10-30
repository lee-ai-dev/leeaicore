from django.test import TestCase
from rest_framework.test import APIClient
from django.urls import reverse

from accounts.models import User, Restaurant
from api.models import Dish, Table, Order, Reservation, Complaint, Payment
from leeaicore.sysutils.constants import PaymentStatus


class APIFeaturesTest(TestCase):
	def setUp(self):
		self.client = APIClient()
		self.user = User.objects.create_user(
			email="u@example.com", phone="1234567890", password="pass1234", name="User"
		)
		self.restaurant_owner = User.objects.create_user(
			email="r@example.com", phone="1234567891", password="pass1234", name="Rest Owner"
		)
		self.restaurant = Restaurant.objects.create(
			user=self.restaurant_owner, name="Test Resto", phone="111222333"
		)
		self.dish1 = Dish.objects.create(
			restaurant=self.restaurant, name="Fufu", description="Fufu & Soup",
			currency="GHC", in_stock=True, price=50, type="MAIN", tag="ghanaian"
		)
		self.dish2 = Dish.objects.create(
			restaurant=self.restaurant, name="Jollof", description="Jollof Rice",
			currency="GHC", in_stock=True, price=40, type="MAIN", tag="ghanaian"
		)
		self.table = Table.objects.create(
			table_id="T1", capacity=4, type="REG", currency="GHC", price=10.0, available=True
		)
		self.client.force_authenticate(user=self.user)

	def test_menu_retrieve(self):
		url = reverse("menu")
		res = self.client.get(url, {"restaurant_rid": self.restaurant.rid})
		self.assertEqual(res.status_code, 200)
		self.assertGreaterEqual(len(res.data), 2)
		names = [d["name"] for d in res.data]
		self.assertIn("Fufu", names)

	def test_place_order_and_status(self):
		url = reverse("place_order")
		payload = {
			"restaurant_rid": self.restaurant.rid,
			"items": [
				{"dish_id": self.dish1.id, "quantity": 2},
				{"dish_id": self.dish2.id, "quantity": 1},
			],
			"delivery_address": "Somewhere",
		}
		res = self.client.post(url, payload, format="json")
		self.assertEqual(res.status_code, 200, res.data)
		ord_id = res.data["ord_id"]
		self.assertEqual(res.data["total_price"], 2 * 50 + 1 * 40)

		# status check
		status_url = reverse("order_status", kwargs={"ord_id": ord_id})
		res2 = self.client.get(status_url)
		self.assertEqual(res2.status_code, 200)
		self.assertEqual(res2.data["ord_id"], ord_id)

	def test_payment_flow(self):
		# place order
		order_res = self.client.post(reverse("place_order"), {
			"restaurant_rid": self.restaurant.rid,
			"items": [{"dish_id": self.dish1.id, "quantity": 1}],
			"delivery_address": "Somewhere",
		}, format="json")
		self.assertEqual(order_res.status_code, 200)
		ord_id = order_res.data["ord_id"]

		# create intent
		intent_res = self.client.post(reverse("payment_intent"), {"ord_id": ord_id}, format="json")
		self.assertEqual(intent_res.status_code, 200, intent_res.data)
		self.assertEqual(intent_res.data["status"], PaymentStatus.PENDING.value)

		# confirm
		confirm_res = self.client.post(reverse("payment_confirm", kwargs={"ord_id": ord_id}), {"transaction_id": "txn_123"}, format="json")
		self.assertEqual(confirm_res.status_code, 200)
		self.assertEqual(confirm_res.data["status"], PaymentStatus.SUCCEEDED.value)

		# verify order updated
		order = Order.objects.get(ord_id=ord_id)
		self.assertEqual(order.payment_status.lower(), "paid")

	def test_reservation(self):
		res = self.client.post(reverse("reservations"), {
			"table": self.table.id,
			"restaurant": self.restaurant.id,
		}, format="json")
		self.assertEqual(res.status_code, 200, res.data)
		reservation_id = res.data["id"]
		self.assertTrue(Reservation.objects.filter(id=reservation_id).exists())
		# table should be unavailable now
		self.table.refresh_from_db()
		self.assertFalse(self.table.available)

	def test_complaint(self):
		res = self.client.post(reverse("complaints"), {
			"restaurant": self.restaurant.id,
			"subject": "Food was cold",
			"message": "Please look into it",
		}, format="json")
		self.assertEqual(res.status_code, 200, res.data)
		self.assertTrue(Complaint.objects.filter(id=res.data["id"]).exists())

	def test_chatbot_intent(self):
		# works even without OPENAI key (fallback)
		res = self.client.post(reverse("chatbot_intent"), {"message": "show me the menu"}, format="json")
		self.assertEqual(res.status_code, 200)
		self.assertIn("intent", res.data)
