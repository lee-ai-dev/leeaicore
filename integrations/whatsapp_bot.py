import re
import secrets
from datetime import datetime
from typing import Any, Dict, List, Tuple

from django.db import transaction
from django.utils import timezone

from accounts.models import Restaurant, User
from api.models import Dish, Order, OrderItem, Reservation, Table
from api.services import enforce_subscription_limit

from .models import WhatsAppContact, WhatsAppIntegration, WhatsAppSession


WELCOME_TEXT = (
    "Welcome!\n"
    "Reply with one of: Order, Reservation, Menu\n\n"
    "You can also type: reset"
)


def reply_text(text: str) -> Dict[str, Any]:
    return {'kind': 'text', 'text': text}


def reply_buttons(body: str, buttons: List[Dict[str, str]]) -> Dict[str, Any]:
    return {'kind': 'buttons', 'body': body, 'buttons': buttons}


def reply_list(body: str, button_text: str, sections: List[Dict[str, Any]]) -> Dict[str, Any]:
    return {'kind': 'list', 'body': body, 'button_text': button_text, 'sections': sections}


def _norm(text: str) -> str:
    return (text or '').strip()


def _norm_lower(text: str) -> str:
    return _norm(text).lower()


def _get_or_create_guest_user(*, wa_id: str, name: str | None = None) -> User:
    """Create a local user record for a WhatsApp end-user."""
    existing = User.objects.filter(phone=wa_id).first()
    if existing:
        return existing
    email = f"wa_{wa_id}@guest.local"
    password = secrets.token_urlsafe(18)
    user = User.objects.create_user(
        email=email,
        password=password,
        phone=wa_id,
        name=name or f"WhatsApp User {wa_id}",
    )
    user.phone_verified = True
    user.save(update_fields=['phone_verified'])
    return user


def get_or_create_contact(integration: WhatsAppIntegration, *, wa_id: str, name: str = '') -> WhatsAppContact:
    contact = WhatsAppContact.objects.filter(integration=integration, wa_id=wa_id).select_related('user').first()
    if contact:
        if name and not contact.name:
            contact.name = name
            contact.save(update_fields=['name'])
        if not contact.user:
            contact.user = _get_or_create_guest_user(wa_id=wa_id, name=contact.name or name)
            contact.save(update_fields=['user'])
        return contact

    user = _get_or_create_guest_user(wa_id=wa_id, name=name)
    return WhatsAppContact.objects.create(integration=integration, wa_id=wa_id, name=name or '', user=user)


def get_open_session(integration: WhatsAppIntegration, contact: WhatsAppContact) -> WhatsAppSession:
    session = (
        WhatsAppSession.objects.filter(integration=integration, contact=contact, is_open=True)
        .order_by('-updated_at')
        .first()
    )
    if session:
        return session
    return WhatsAppSession.objects.create(integration=integration, contact=contact, state='START', context={}, is_open=True)


def reset_session(session: WhatsAppSession) -> None:
    session.state = 'START'
    session.context = {}
    session.is_open = True
    session.save(update_fields=['state', 'context', 'is_open', 'updated_at'])


def build_menu_text(restaurant: Restaurant, limit: int = 10) -> Tuple[str, List[int]]:
    dishes = list(Dish.objects.filter(restaurant=restaurant, in_stock=True).order_by('name')[:limit])
    if not dishes:
        return "No dishes available right now.", []
    lines = ["Menu:"]
    dish_ids: List[int] = []
    for idx, d in enumerate(dishes, start=1):
        lines.append(f"{idx}. {d.name} - {d.currency}{d.price}")
        dish_ids.append(d.id)
    lines.append("\nTo order, reply: 1x2, 3x1 (number x quantity)")
    return "\n".join(lines), dish_ids


def build_tables_text(restaurant: Restaurant, limit: int = 10) -> Tuple[str, List[int]]:
    tables = list(Table.objects.filter(restaurant=restaurant, available=True).order_by('table_id')[:limit])
    if not tables:
        return "No tables are currently available.", []
    lines = ["Available tables:"]
    table_ids: List[int] = []
    for idx, t in enumerate(tables, start=1):
        desc = f" ({t.description})" if t.description else ""
        lines.append(f"{idx}. Table {t.table_id} - seats {t.capacity}{desc}")
        table_ids.append(t.id)
    lines.append("\nTo reserve, reply with the number (e.g. 1)")
    return "\n".join(lines), table_ids


def build_tables_list_reply(restaurant: Restaurant, limit: int = 10) -> Tuple[Dict[str, Any] | None, List[int]]:
    tables = list(Table.objects.filter(restaurant=restaurant, available=True).order_by('table_id')[:limit])
    if not tables:
        return None, []

    table_ids: List[int] = []
    rows: List[Dict[str, str]] = []
    for idx, t in enumerate(tables, start=1):
        table_ids.append(t.id)
        desc = f"Seats {t.capacity}" + (f" · {t.description}" if t.description else "")
        rows.append({'id': str(idx), 'title': f"Table {t.table_id}", 'description': desc})

    sections = [{'title': 'Available tables', 'rows': rows}]
    return reply_list('Select a table to reserve:', 'Choose', sections), table_ids


_ITEM_RE = re.compile(r"^\s*(\d+)\s*(?:x\s*(\d+))?\s*$", re.IGNORECASE)


def parse_item_selection(text: str) -> List[Tuple[int, int]]:
    """Parse selections like: '1x2, 3x1' -> [(1,2),(3,1)]"""
    parts = [p.strip() for p in (text or '').split(',') if p.strip()]
    out: List[Tuple[int, int]] = []
    for part in parts:
        m = _ITEM_RE.match(part)
        if not m:
            return []
        idx = int(m.group(1))
        qty = int(m.group(2) or '1')
        if idx <= 0 or qty <= 0:
            return []
        out.append((idx, qty))
    return out


def parse_datetime_text(text: str) -> datetime | None:
    """Parse 'YYYY-MM-DD HH:MM'"""
    try:
        dt = datetime.strptime(text.strip(), '%Y-%m-%d %H:%M')
    except Exception:
        return None
    # Treat as local timezone
    if timezone.is_naive(dt):
        dt = timezone.make_aware(dt, timezone.get_current_timezone())
    return dt


@transaction.atomic
def handle_inbound_text(
    *,
    integration: WhatsAppIntegration,
    contact: WhatsAppContact,
    text: str,
) -> List[Any]:
    """Return a list of reply messages."""

    session = get_open_session(integration, contact)
    raw = _norm(text)
    lower = _norm_lower(text)

    if lower in {'reset', 'start', 'restart', 'menu'} and session.state != 'START':
        reset_session(session)

    if lower in {'help', '?'}:
        return [reply_text(WELCOME_TEXT)]

    if session.state == 'START':
        if lower in {'', 'hi', 'hello', 'hey', 'start'}:
            return [
                reply_buttons(
                    'Welcome! Choose an option:',
                    [
                        {'id': 'order', 'title': 'Order'},
                        {'id': 'reservation', 'title': 'Reservation'},
                        {'id': 'menu', 'title': 'Menu'},
                    ],
                )
            ]

        if lower in {'menu'}:
            menu_text, _ = build_menu_text(integration.restaurant)
            return [reply_text(menu_text)]

        if lower in {'order'}:
            # Enforce subscription order limit
            current_orders = Order.objects.filter(restaurant=integration.restaurant).count()
            try:
                enforce_subscription_limit(integration.restaurant, kind='orders', current_count=current_orders)
            except ValueError as e:
                return [str(e)]

            menu_text, dish_ids = build_menu_text(integration.restaurant)
            session.state = 'ORDER_PICK_ITEMS'
            session.context = {'dish_ids': dish_ids}
            session.save(update_fields=['state', 'context', 'updated_at'])
            return [reply_text(menu_text)]

        if lower in {'reservation', 'reserve'}:
            current_res = Reservation.objects.filter(restaurant=integration.restaurant).count()
            try:
                enforce_subscription_limit(integration.restaurant, kind='reservations', current_count=current_res)
            except ValueError as e:
                return [str(e)]

            list_reply, table_ids = build_tables_list_reply(integration.restaurant)
            if not table_ids:
                tables_text, _ = build_tables_text(integration.restaurant)
                return [reply_text(tables_text)]
            session.state = 'RESERVE_PICK_TABLE'
            session.context = {'table_ids': table_ids}
            session.save(update_fields=['state', 'context', 'updated_at'])
            return [list_reply]

        return [reply_text(WELCOME_TEXT)]

    if session.state == 'ORDER_PICK_ITEMS':
        dish_ids: List[int] = list((session.context or {}).get('dish_ids') or [])
        sel = parse_item_selection(raw)
        if not sel:
            return [reply_text("Sorry, I didn't understand. Reply like: 1x2, 3x1")]

        cart: List[Dict[str, int]] = []
        for idx, qty in sel:
            if idx > len(dish_ids):
                return [reply_text(f"Item {idx} is not in the menu list. Please try again.")]
            cart.append({'dish_id': dish_ids[idx - 1], 'qty': qty})

        session.state = 'ORDER_ADDRESS'
        session.context = {'cart': cart}
        session.save(update_fields=['state', 'context', 'updated_at'])
        return [reply_text("Great. What delivery address should we use?")]

    if session.state == 'ORDER_ADDRESS':
        address = raw
        if len(address) < 4:
            return [reply_text("Please send a valid delivery address.")]

        cart = (session.context or {}).get('cart') or []
        if not cart:
            reset_session(session)
            return [reply_text("Your cart is empty. Reply 'Order' to start again.")]

        # Create order + items
        order = Order.objects.create(
            user=contact.user,
            restaurant=integration.restaurant,
            delivery_address=address,
            payment_method='Cash on Delivery',
            payment_status='Unpaid',
            status='Pending',
        )
        items = []
        for it in cart:
            dish = Dish.objects.get(id=it['dish_id'], restaurant=integration.restaurant)
            items.append(OrderItem.objects.create(dish=dish, quantity=int(it['qty'])))
        order.items.add(*items)
        order.refresh_from_db()

        reset_session(session)
        return [reply_text(f"Order placed!\nOrder ID: {order.ord_id}\nTotal: {order.currency}{order.total_price}")]

    if session.state == 'RESERVE_PICK_TABLE':
        table_ids: List[int] = list((session.context or {}).get('table_ids') or [])
        try:
            idx = int(raw)
        except Exception:
            return [reply_text("Reply with the table number (e.g. 1).")]
        if idx <= 0 or idx > len(table_ids):
            return [reply_text("That table number is not valid. Try again.")]

        session.state = 'RESERVE_PICK_DATETIME'
        session.context = {'table_id': table_ids[idx - 1]}
        session.save(update_fields=['state', 'context', 'updated_at'])
        return [reply_text("When should we reserve it? Reply like: 2025-12-31 19:30")]

    if session.state == 'RESERVE_PICK_DATETIME':
        dt = parse_datetime_text(raw)
        if not dt:
            return [reply_text("Please use format: YYYY-MM-DD HH:MM (e.g. 2025-12-31 19:30)")]

        table_id = (session.context or {}).get('table_id')
        if not table_id:
            reset_session(session)
            return [reply_text("Reservation context missing. Reply 'Reservation' to start again.")]

        table = Table.objects.select_for_update().filter(id=table_id, restaurant=integration.restaurant).first()
        if not table or not table.available:
            reset_session(session)
            return [reply_text("That table is no longer available. Reply 'Reservation' to try again.")]

        res = Reservation.objects.create(
            table=table,
            restaurant=integration.restaurant,
            user=contact.user,
            date=dt.date(),
            time=dt.time(),
        )
        table.available = False
        table.save(update_fields=['available'])

        reset_session(session)
        return [reply_text(f"Reservation created!\nReservation ID: {res.id}\nTable: {table.table_id}\nWhen: {dt.strftime('%Y-%m-%d %H:%M')}")]

    reset_session(session)
    return [reply_text(WELCOME_TEXT)]
