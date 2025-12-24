from django.db import models

from accounts.models import Restaurant, User
from leeaicore.sysutils.models import TimeStampedModel


class WhatsAppIntegration(TimeStampedModel):
	"""Per-vendor WhatsApp Cloud API configuration.

	A dedicated WhatsApp Business phone number maps to a unique `phone_number_id`.
	We route inbound webhooks using that id to the correct restaurant.
	"""

	restaurant = models.OneToOneField(Restaurant, on_delete=models.CASCADE, related_name='whatsapp_integration')
	enabled = models.BooleanField(default=True)
	display_name = models.CharField(max_length=120, blank=True, default='')
	phone_number_id = models.CharField(max_length=64, unique=True)
	waba_id = models.CharField(max_length=64, blank=True, null=True)
	business_account_id = models.CharField(max_length=64, blank=True, null=True)

	# Optional per-integration token. If empty, settings.WHATSAPP_ACCESS_TOKEN is used.
	access_token = models.TextField(blank=True, null=True)

	last_inbound_at = models.DateTimeField(blank=True, null=True)
	last_outbound_at = models.DateTimeField(blank=True, null=True)
	last_error = models.TextField(blank=True, null=True)

	def __str__(self) -> str:
		return f"WhatsAppIntegration({self.restaurant_id}, {self.phone_number_id})"


class WhatsAppContact(TimeStampedModel):
	"""A WhatsApp end-user as seen by a vendor bot."""

	integration = models.ForeignKey(WhatsAppIntegration, on_delete=models.CASCADE, related_name='contacts')
	wa_id = models.CharField(max_length=20)  # WhatsApp ID (typically E.164 digits)
	name = models.CharField(max_length=120, blank=True, default='')
	user = models.ForeignKey(User, on_delete=models.SET_NULL, null=True, blank=True, related_name='whatsapp_contacts')

	class Meta:
		unique_together = ('integration', 'wa_id')

	def __str__(self) -> str:
		return f"WAContact({self.wa_id})"


class WhatsAppSession(TimeStampedModel):
	"""Simple state machine session per contact/vendor."""

	STATE_CHOICES = [
		('START', 'START'),
		('ORDER_PICK_ITEMS', 'ORDER_PICK_ITEMS'),
		('ORDER_ADDRESS', 'ORDER_ADDRESS'),
		('RESERVE_PICK_TABLE', 'RESERVE_PICK_TABLE'),
		('RESERVE_PICK_DATETIME', 'RESERVE_PICK_DATETIME'),
	]

	integration = models.ForeignKey(WhatsAppIntegration, on_delete=models.CASCADE, related_name='sessions')
	contact = models.ForeignKey(WhatsAppContact, on_delete=models.CASCADE, related_name='sessions')
	state = models.CharField(max_length=40, choices=STATE_CHOICES, default='START')
	context = models.JSONField(default=dict, blank=True)
	is_open = models.BooleanField(default=True)

	class Meta:
		indexes = [
			models.Index(fields=['integration', 'contact', 'is_open', 'updated_at']),
		]

	def __str__(self) -> str:
		return f"WASession({self.contact.wa_id}, {self.state})"


class WhatsAppInboundMessage(TimeStampedModel):
	"""Inbound webhook message log (for idempotency + debugging)."""

	integration = models.ForeignKey(WhatsAppIntegration, on_delete=models.CASCADE, related_name='inbound_messages')
	contact = models.ForeignKey(WhatsAppContact, on_delete=models.SET_NULL, null=True, blank=True, related_name='inbound_messages')
	message_id = models.CharField(max_length=128, unique=True)
	from_wa_id = models.CharField(max_length=20)
	message_type = models.CharField(max_length=40, blank=True, default='')
	text = models.TextField(blank=True, default='')
	raw = models.JSONField(default=dict, blank=True)
	processed = models.BooleanField(default=False)
	error = models.TextField(blank=True, null=True)

	def __str__(self) -> str:
		return f"Inbound({self.message_id})"


class WhatsAppOutboundMessage(TimeStampedModel):
	"""Outbound message log."""

	integration = models.ForeignKey(WhatsAppIntegration, on_delete=models.CASCADE, related_name='outbound_messages')
	contact = models.ForeignKey(WhatsAppContact, on_delete=models.SET_NULL, null=True, blank=True, related_name='outbound_messages')
	to_wa_id = models.CharField(max_length=20)
	provider_message_id = models.CharField(max_length=128, blank=True, null=True)
	message_type = models.CharField(max_length=40, blank=True, default='text')
	text = models.TextField(blank=True, default='')
	raw = models.JSONField(default=dict, blank=True)
	sent_ok = models.BooleanField(default=False)
	error = models.TextField(blank=True, null=True)

	def __str__(self) -> str:
		return f"Outbound(to={self.to_wa_id}, ok={self.sent_ok})"
