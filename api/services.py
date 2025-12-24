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

    def list_banks(
        self,
        *,
        currency: str | None = None,
        country: str | None = None,
        per_page: int = 200,
        page: int = 1,
    ):
        """List banks supported by Paystack.

        Paystack supports filtering by currency and/or country depending on region.
        Returns Paystack's bank list payload (list of dicts).
        """
        url = f"{self.base_url}/bank"
        params: dict[str, object] = {
            'perPage': per_page,
            'page': page,
        }
        if currency:
            params['currency'] = currency
        if country:
            params['country'] = country

        resp = requests.get(url, headers=self._headers, params=params, timeout=15)
        data = resp.json() if resp.content else {}
        if resp.status_code >= 400 or not data.get('status'):
            message = data.get('message') or 'Paystack list banks failed'
            raise ValueError(message)
        return data.get('data') or []

    def resolve_bank_account(self, *, account_number: str, bank_code: str):
        """Resolve/verify a bank account number with Paystack.

        Paystack endpoint: GET /bank/resolve?account_number=...&bank_code=...
        Returns Paystack 'data' payload (dict).
        """
        url = f"{self.base_url}/bank/resolve"
        params = {
            'account_number': account_number,
            'bank_code': bank_code,
        }
        resp = requests.get(url, headers=self._headers, params=params, timeout=15)
        data = resp.json() if resp.content else {}
        if resp.status_code >= 400 or not data.get('status'):
            message = data.get('message') or 'Paystack bank account resolve failed'
            raise ValueError(message)
        return data.get('data') or {}
    
    


def get_active_subscription(restaurant):
    """Return the active subscription for a restaurant, if any."""
    from api.models import Subscription
    return Subscription.objects.filter(restaurant=restaurant, status='ACTIVE').order_by('-end_date').first()


def enforce_subscription_limit(restaurant, *, kind: str, current_count: int):
    """Enforce subscription limits for a restaurant.

    kind: 'dishes' | 'tables' | 'orders' | 'reservations'
    Raises ValueError if the limit is exceeded or no active subscription exists.
    """
    sub = get_active_subscription(restaurant)
    if not sub:
        raise ValueError('No active subscription')

    package = sub.package
    if kind == 'dishes':
        limit = package.max_dishes
    elif kind == 'tables':
        limit = package.max_tables
    elif kind == 'orders':
        limit = package.max_orders
    elif kind == 'reservations':
        limit = package.max_reservations
    else:
        raise ValueError('Unknown subscription limit type')

    if current_count >= limit:
        raise ValueError(f'Subscription limit reached for {kind}')

    return sub
