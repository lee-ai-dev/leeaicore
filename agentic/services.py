import json
from typing import Any, Dict, Optional

from django.conf import settings

try:
	# New OpenAI SDK
	from openai import OpenAI  # type: ignore
	_HAS_OPENAI = True
except Exception:
	_HAS_OPENAI = False


INTENT_SCHEMA = {
	"type": "object",
	"properties": {
		"intent": {
			"type": "string",
			"enum": [
				"PlaceOrder",
				"RetrieveMenu",
				"CheckOrderStatus",
				"SubmitComplaint",
				"PaymentProcessing",
				"TableReservation",
				"Unknown",
			],
		},
		"entities": {
			"type": "object",
			"additionalProperties": True
		}
	},
	"required": ["intent", "entities"]
}


SYSTEM_PROMPT = """You are an intent classifier for a restaurant platform.
Return strict JSON that matches the provided JSON schema. Do not include any text outside JSON.
Recognized intents:
- PlaceOrder
- RetrieveMenu
- CheckOrderStatus
- SubmitComplaint
- PaymentProcessing
- TableReservation
- Unknown

Entities examples:
- PlaceOrder: {restaurant_rid, items:[{dish_name or dish_id, quantity}], delivery_address}
- RetrieveMenu: {restaurant_rid?, query?}
- CheckOrderStatus: {ord_id}
- SubmitComplaint: {subject, message, ord_id?}
- PaymentProcessing: {ord_id, action:create_intent|confirm, txn_id?}
- TableReservation: {restaurant_rid, table_id, datetime?}
If unsure, pick the closest and fill params conservatively.
"""


class IntentEngine:
	def __init__(self, model: Optional[str] = None):
		self.model = model or getattr(settings, "OPENAI_MODEL", "gpt-4o-mini")
		self.enabled = _HAS_OPENAI and bool(getattr(settings, "OPENAI_API_KEY", ""))

		if self.enabled:
			self.client = OpenAI(api_key=settings.OPENAI_API_KEY)

	def classify(self, message: str) -> Dict[str, Any]:
		if not self.enabled:
			# Fallback heuristic
			lower = message.lower()
			if any(k in lower for k in ["menu", "dish", "meal", "food list"]):
				return {"intent": "RetrieveMenu", "entities": {}}
			if any(k in lower for k in ["order", "buy", "purchase"]):
				return {"intent": "PlaceOrder", "entities": {}}
			if "status" in lower:
				return {"intent": "CheckOrderStatus", "entities": {}}
			if "complaint" in lower or "issue" in lower or "problem" in lower:
				return {"intent": "SubmitComplaint", "entities": {}}
			if "pay" in lower or "payment" in lower:
				return {"intent": "PaymentProcessing", "entities": {}}
			if "table" in lower or "reserve" in lower or "reservation" in lower:
				return {"intent": "TableReservation", "entities": {}}
			return {"intent": "Unknown", "entities": {}}

		try:
			completion = self.client.chat.completions.create(
				model=self.model,
				temperature=0.1,
				messages=[
					{"role": "system", "content": SYSTEM_PROMPT},
					{"role": "user", "content": message},
				],
				response_format={"type": "json_object"},
			)
			raw = completion.choices[0].message.content or "{}"
			data = json.loads(raw)
			# Minimal validation to match schema shape
			if "intent" not in data or "entities" not in data:
				return {"intent": "Unknown", "entities": {}}
			return data
		except Exception:
			# Defensive fallback
			return {"intent": "Unknown", "entities": {}}
