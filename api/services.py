import requests
from django.conf import settings


class PaystackClient:
    """Minimal Paystack client for initializing and verifying transactions."""

    def __init__(self, secret_key: str | None = None, base_url: str | None = None):
        self.secret_key = secret_key or settings.PAYSTACK_SECRET_KEY
        self.base_url = (base_url or settings.PAYSTACK_BASE_URL).rstrip('/')
        self._headers = {
            'Authorization': f'Bearer {self.secret_key}',
            'Content-Type': 'application/json',
        }

    def initialize(self, email: str, amount_minor: int, reference: str, currency: str = 'GHS', callback_url: str | None = None):
        url = f"{self.base_url}/transaction/initialize"
        payload = {
            'email': email,
            'amount': amount_minor,  # Paystack expects minor units (kobo/pesewas)
            'reference': reference,
            'currency': currency,
        }
        if callback_url:
            payload['callback_url'] = callback_url
        resp = requests.post(url, json=payload, headers=self._headers, timeout=15)
        data = resp.json() if resp.content else {}
        if resp.status_code >= 400 or not data.get('status'):
            message = data.get('message') or 'Paystack initialization failed'
            raise ValueError(message)
        return data['data']  # contains authorization_url, access_code, reference

    def verify(self, reference: str):
        url = f"{self.base_url}/transaction/verify/{reference}"
        resp = requests.get(url, headers=self._headers, timeout=15)
        data = resp.json() if resp.content else {}
        if resp.status_code >= 400 or not data.get('status'):
            message = data.get('message') or 'Paystack verification failed'
            raise ValueError(message)
        return data['data']  # contains status etc.
