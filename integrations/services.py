import hashlib
import hmac
import json
from dataclasses import dataclass
from typing import Any, Dict, List, Optional

import requests
from django.conf import settings
from django.utils import timezone


@dataclass(frozen=True)
class WhatsAppMessageEvent:
    phone_number_id: str
    wa_id: str
    message_id: str
    message_type: str
    text: str
    raw: Dict[str, Any]


def verify_whatsapp_signature(*, app_secret: str, body: bytes, signature_header: str | None) -> bool:
    """Validate Meta X-Hub-Signature-256 header.

    Header format: sha256=<hexdigest>
    """
    if not app_secret:
        return False
    if not signature_header:
        return False
    if not signature_header.startswith('sha256='):
        return False

    their_sig = signature_header.split('=', 1)[1].strip()
    mac = hmac.new(app_secret.encode('utf-8'), msg=body, digestmod=hashlib.sha256).hexdigest()
    return hmac.compare_digest(mac, their_sig)


def extract_message_events(payload: Dict[str, Any]) -> List[WhatsAppMessageEvent]:
    """Extract inbound message events from a WhatsApp Cloud API webhook payload."""

    events: List[WhatsAppMessageEvent] = []
    for entry in payload.get('entry') or []:
        for change in entry.get('changes') or []:
            value = change.get('value') or {}
            metadata = value.get('metadata') or {}
            phone_number_id = str(metadata.get('phone_number_id') or '')
            messages = value.get('messages') or []
            for msg in messages:
                msg_type = msg.get('type') or ''
                msg_id = msg.get('id') or ''
                wa_id = msg.get('from') or ''

                text = ''
                if msg_type == 'text':
                    text = (msg.get('text') or {}).get('body') or ''
                elif msg_type == 'button':
                    text = (msg.get('button') or {}).get('text') or ''
                elif msg_type == 'interactive':
                    interactive = msg.get('interactive') or {}
                    itype = interactive.get('type')
                    if itype == 'button_reply':
                        br = interactive.get('button_reply') or {}
                        text = (br.get('id') or br.get('title') or '')
                    elif itype == 'list_reply':
                        lr = interactive.get('list_reply') or {}
                        text = (lr.get('id') or lr.get('title') or '')

                if phone_number_id and wa_id and msg_id:
                    events.append(
                        WhatsAppMessageEvent(
                            phone_number_id=phone_number_id,
                            wa_id=str(wa_id),
                            message_id=str(msg_id),
                            message_type=str(msg_type),
                            text=str(text or '').strip(),
                            raw=msg,
                        )
                    )
    return events


class WhatsAppCloudClient:
    """Minimal WhatsApp Cloud API client."""

    def __init__(
        self,
        *,
        access_token: Optional[str] = None,
        base_url: Optional[str] = None,
        api_version: Optional[str] = None,
        timeout: int = 15,
    ):
        self.access_token = access_token or getattr(settings, 'WHATSAPP_ACCESS_TOKEN', '')
        self.base_url = (base_url or getattr(settings, 'WHATSAPP_BASE_URL', 'https://graph.facebook.com')).rstrip('/')
        self.api_version = api_version or getattr(settings, 'WHATSAPP_GRAPH_API_VERSION', 'v20.0')
        self.timeout = timeout

    def _headers(self) -> Dict[str, str]:
        return {
            'Authorization': f'Bearer {self.access_token}',
            'Content-Type': 'application/json',
        }

    def send_text(self, *, phone_number_id: str, to: str, text: str, preview_url: bool = False) -> Dict[str, Any]:
        if not self.access_token:
            raise ValueError('WHATSAPP access token not configured')
        url = f"{self.base_url}/{self.api_version}/{phone_number_id}/messages"
        payload = {
            'messaging_product': 'whatsapp',
            'to': to,
            'type': 'text',
            'text': {
                'preview_url': bool(preview_url),
                'body': text,
            },
        }
        resp = requests.post(url, data=json.dumps(payload), headers=self._headers(), timeout=self.timeout)
        data = resp.json() if resp.content else {}
        if resp.status_code >= 400:
            raise ValueError((data.get('error') or {}).get('message') or 'WhatsApp send failed')
        return data

    def send_buttons(
        self,
        *,
        phone_number_id: str,
        to: str,
        body: str,
        buttons: List[Dict[str, str]],
    ) -> Dict[str, Any]:
        """Send interactive button message.

        buttons: list of {"id": "...", "title": "..."}
        """
        if not self.access_token:
            raise ValueError('WHATSAPP access token not configured')
        url = f"{self.base_url}/{self.api_version}/{phone_number_id}/messages"
        payload = {
            'messaging_product': 'whatsapp',
            'to': to,
            'type': 'interactive',
            'interactive': {
                'type': 'button',
                'body': {'text': body},
                'action': {
                    'buttons': [
                        {
                            'type': 'reply',
                            'reply': {'id': b['id'], 'title': b['title']},
                        }
                        for b in buttons
                    ]
                },
            },
        }
        resp = requests.post(url, data=json.dumps(payload), headers=self._headers(), timeout=self.timeout)
        data = resp.json() if resp.content else {}
        if resp.status_code >= 400:
            raise ValueError((data.get('error') or {}).get('message') or 'WhatsApp send failed')
        return data

    def send_list(
        self,
        *,
        phone_number_id: str,
        to: str,
        body: str,
        button_text: str,
        sections: List[Dict[str, Any]],
    ) -> Dict[str, Any]:
        """Send interactive list message.

        sections format (Meta):
          [{"title": "...", "rows": [{"id": "...", "title": "...", "description": "..."}, ...]}]
        """
        if not self.access_token:
            raise ValueError('WHATSAPP access token not configured')
        url = f"{self.base_url}/{self.api_version}/{phone_number_id}/messages"
        payload = {
            'messaging_product': 'whatsapp',
            'to': to,
            'type': 'interactive',
            'interactive': {
                'type': 'list',
                'body': {'text': body},
                'action': {
                    'button': button_text,
                    'sections': sections,
                },
            },
        }
        resp = requests.post(url, data=json.dumps(payload), headers=self._headers(), timeout=self.timeout)
        data = resp.json() if resp.content else {}
        if resp.status_code >= 400:
            raise ValueError((data.get('error') or {}).get('message') or 'WhatsApp send failed')
        return data

    def get_phone_number_details(self, *, phone_number_id: str) -> Dict[str, Any]:
        """Fetch WhatsApp phone number metadata from Graph API.

        Useful as a health check to confirm phone_number_id + token are valid.
        """
        if not self.access_token:
            raise ValueError('WHATSAPP access token not configured')
        url = f"{self.base_url}/{self.api_version}/{phone_number_id}"
        params = {
            # Keep it minimal and stable.
            'fields': 'id,display_phone_number,verified_name,quality_rating,code_verification_status',
        }
        resp = requests.get(url, params=params, headers=self._headers(), timeout=self.timeout)
        data = resp.json() if resp.content else {}
        if resp.status_code >= 400:
            raise ValueError((data.get('error') or {}).get('message') or 'WhatsApp health check failed')
        return data


def build_integrations_summary() -> dict:
    """Return integrations summary in the same shape as api.serializers.IntegrationsSummaryDataSerializer."""
    from api.models import Payment
    from .models import WhatsAppIntegration

    now = timezone.now()

    # Paystack: treat as active if secret is configured.
    paystack_active = bool(getattr(settings, 'PAYSTACK_SECRET_KEY', ''))
    paystack_clients = Payment.objects.exclude(provider__iexact='MOCK').count() if paystack_active else 0

    # WhatsApp: count enabled integrations.
    wa_qs = WhatsAppIntegration.objects.all()
    wa_enabled = wa_qs.filter(enabled=True)
    whatsapp_clients = wa_enabled.count()
    wa_lastsync = (
        wa_enabled.order_by('-last_inbound_at').values_list('last_inbound_at', flat=True).first()
        or wa_enabled.order_by('-last_outbound_at').values_list('last_outbound_at', flat=True).first()
        or now
    )
    whatsapp_status = 'active' if whatsapp_clients > 0 else 'inactive'

    # Stripe placeholder
    stripe_status = 'inactive'

    data = [
        {
            'integration': 'paystack',
            'clients': int(paystack_clients),
            'category': 'payment',
            'status': 'active' if paystack_active else 'inactive',
            'lastsync': now,
        },
        {
            'integration': 'whatsapp',
            'clients': int(whatsapp_clients),
            'category': 'messaging',
            'status': whatsapp_status,
            'lastsync': wa_lastsync,
        },
        {
            'integration': 'stripe',
            'clients': 0,
            'category': 'payment',
            'status': stripe_status,
            'lastsync': now,
        },
    ]

    total_clients = sum(item['clients'] for item in data)
    supported_integrations = len(data)
    failed_integrations = sum(1 for item in data if item['status'] != 'active')
    most_used = max(data, key=lambda x: x['clients'])['integration'] if data else None

    return {
        'summary': {
            'total_clients': total_clients,
            'supported_integrations': supported_integrations,
            'failed_integrations': failed_integrations,
            'most_used_integration': most_used,
        },
        'data': data,
    }


def build_integrations_catalog() -> list[dict]:
    """Return supported integrations with vendor counts.

    Shape: [{integration, category, vendors, status}, ...]
    """
    from api.models import Payment
    from .models import WhatsAppIntegration

    paystack_active = bool(getattr(settings, 'PAYSTACK_SECRET_KEY', ''))
    paystack_vendors = (
        Payment.objects.filter(provider__iexact='PAYSTACK')
        .values_list('order__restaurant_id', flat=True)
        .distinct()
        .count()
        if paystack_active
        else 0
    )

    wa_enabled = WhatsAppIntegration.objects.filter(enabled=True)
    wa_vendors = wa_enabled.count()
    wa_has_token = bool(getattr(settings, 'WHATSAPP_ACCESS_TOKEN', '')) or wa_enabled.exclude(access_token__isnull=True).exclude(access_token='').exists()
    whatsapp_status = 'active' if (wa_vendors > 0 and wa_has_token) else 'inactive'

    # Stripe placeholder
    stripe_status = 'inactive'

    return [
        {
            'integration': 'whatsapp',
            'category': 'messaging',
            'vendors': int(wa_vendors),
            'status': whatsapp_status,
        },
        {
            'integration': 'paystack',
            'category': 'payment',
            'vendors': int(paystack_vendors),
            'status': 'active' if paystack_active else 'inactive',
        },
        {
            'integration': 'stripe',
            'category': 'payment',
            'vendors': 0,
            'status': stripe_status,
        },
    ]
