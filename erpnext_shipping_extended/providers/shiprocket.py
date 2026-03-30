from __future__ import annotations

import base64
import json
import re
import threading
from dataclasses import dataclass
from datetime import datetime, timezone

import frappe
from frappe import _
import requests
from frappe.utils import get_datetime, now_datetime

from .base_provider import BaseShippingProvider


SHIPROCKET_API_BASE_URL = "https://apiv2.shiprocket.in/v1/external"


@dataclass(frozen=True)
class _ShiprocketToken:
	token: str
	expires_at: str | None = None


_token_lock = threading.Lock()
_token_cache: dict[str, _ShiprocketToken] = {}
_TOKEN_CACHE_PREFIX = "shiprocket_token:"
_TOKEN_CACHE_TTL = 3600


def _decode_jwt_expiry(token: str) -> str | None:
	parts = (token or "").split(".")
	if len(parts) != 3:
		return None

	try:
		payload = parts[1]
		padding = "=" * (-len(payload) % 4)
		decoded = base64.urlsafe_b64decode(payload + padding)
		data = json.loads(decoded.decode("utf-8"))
	except Exception:
		return None

	exp = data.get("exp")
	if not exp:
		return None

	try:
		return datetime.fromtimestamp(int(exp), tz=timezone.utc).strftime("%Y-%m-%d %H:%M:%S")
	except Exception:
		return None


def get_cached_shiprocket_auth_status() -> dict[str, str | None]:
	cached = _get_cached_token(frappe.local.site)
	if not cached:
		return {"bearer_token": None, "token_expiry": None}

	return {
		"bearer_token": cached.token,
		"token_expiry": cached.expires_at,
	}


def _token_cache_key(site_key: str) -> str:
	return f"{_TOKEN_CACHE_PREFIX}{site_key}"


def _get_cached_token(site_key: str) -> _ShiprocketToken | None:
	cached = _token_cache.get(site_key)
	if cached and (not cached.expires_at or get_datetime(cached.expires_at) > now_datetime()):
		return cached

	cache_value = frappe.cache().get(_token_cache_key(site_key))
	if not cache_value:
		return None

	try:
		if isinstance(cache_value, str):
			cache_value = json.loads(cache_value)
		token = _ShiprocketToken(
			token=cache_value.get("token"),
			expires_at=cache_value.get("expires_at"),
		)
	except Exception:
		return None

	if not token.token:
		return None

	if token.expires_at and get_datetime(token.expires_at) <= now_datetime():
		_clear_cached_token(site_key)
		return None

	with _token_lock:
		_token_cache[site_key] = token
	return token


def _set_cached_token(site_key: str, token: _ShiprocketToken) -> None:
	with _token_lock:
		_token_cache[site_key] = token

	frappe.cache().set(
		_token_cache_key(site_key),
		{"token": token.token, "expires_at": token.expires_at},
		expires_in_sec=_TOKEN_CACHE_TTL,
	)


def _clear_cached_token(site_key: str) -> None:
	with _token_lock:
		_token_cache.pop(site_key, None)
	frappe.cache().delete_value(_token_cache_key(site_key))


def _validate_email(email: str) -> bool:
	if not email:
		return False
	return bool(re.match(r"^[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}$", str(email).strip()))


def _validate_phone(phone: str) -> bool:
	if not phone:
		return False
	clean_phone = re.sub(r"[^0-9+]", "", str(phone))
	if clean_phone.startswith("+91"):
		clean_phone = clean_phone[3:]
	elif clean_phone.startswith("91") and len(clean_phone) > 10:
		clean_phone = clean_phone[2:]
	return clean_phone.isdigit() and len(clean_phone) == 10


class ShiprocketProvider(BaseShippingProvider):
	provider_name = "Shiprocket"

	def _fetch_order_details(self, order_id: str | int | None) -> dict | None:
		"""Fetch Shiprocket order details so we can reconcile local status with remote state."""
		if not order_id:
			return None

		url = f"{self._get_base_url()}/orders/show/{order_id}"
		response = None
		try:
			response = requests.get(url, headers=self._get_auth_headers(), timeout=30)
			response.raise_for_status()
			result = response.json() or {}
			return result.get("data") or {}
		except Exception:
			frappe.log_error(
				message=frappe.as_json(
					{
						"order_id": order_id,
						"url": url,
						"status_code": getattr(response, "status_code", None),
						"response_text": getattr(response, "text", None),
					}
				),
				title="Shiprocket Order Lookup Failed",
			)
			return None

	def _extract_remote_order_status(self, order_data: dict | None) -> str:
		status = (
			(order_data or {}).get("status")
			or (order_data or {}).get("status_code")
			or (order_data or {}).get("shipment_status")
			or ""
		)
		return str(status).strip()

	def _sync_remote_order_state(self, shipment_doc, order_data: dict | None, *, context: str) -> str | None:
		"""Mirror important Shiprocket order state back to ERPNext when we discover it late."""
		if not order_data:
			return None

		remote_status = self._extract_remote_order_status(order_data)
		if not remote_status:
			return None

		update_data = {}
		status_lower = remote_status.lower()
		if "cancel" in status_lower:
			update_data["status"] = "Cancelled"
		elif remote_status and not shipment_doc.get("tracking_status"):
			update_data["tracking_status"] = remote_status

		summary = f"Shiprocket order status: {remote_status}"
		if context:
			summary = f"{summary} ({context})"
		update_data["tracking_status_info"] = summary[:140]

		extended_data = self._update_extended_data(
			shipment_doc,
			{"last_known_order": order_data},
			context=f"remote order state sync: {context}" if context else "remote order state sync",
		)
		update_data["extended_provider_data"] = frappe.as_json(extended_data)

		try:
			shipment_doc.db_set(update_data)
			shipment_doc.reload()
		except Exception:
			frappe.log_error(
				message=frappe.as_json(
					{
						"shipment": getattr(shipment_doc, "name", None),
						"order_id": shipment_doc.get("shiprocket_order_id"),
						"remote_status": remote_status,
						"context": context,
					}
				),
				title="Shiprocket Order State Sync Failed",
			)

		return remote_status

	def _get_pickup_address_name(self, shipment_doc) -> str:
		"""Prefer custom pickup field when present, else fall back to core Shipment field."""
		pickup_address_name = shipment_doc.get("pickup_from_address") or shipment_doc.get("pickup_address_name")
		if not pickup_address_name:
			frappe.throw(
				_("Please select a Pickup From Address in the Shipment."),
				title=_("Missing Pickup Address"),
			)
		return pickup_address_name

	def _get_pickup_address(self, shipment_doc):
		return frappe.get_doc("Address", self._get_pickup_address_name(shipment_doc))

	def _load_extended_data(self, shipment_doc) -> dict:
		try:
			data = json.loads(getattr(shipment_doc, "extended_provider_data", None) or "{}")
		except Exception:
			data = {}
		return data if isinstance(data, dict) else {}

	def _update_extended_data(self, shipment_doc, new_data: dict | None, *, context: str | None = None) -> dict:
		existing = self._load_extended_data(shipment_doc)
		shiprocket_data = existing.setdefault("shiprocket", {})
		if isinstance(new_data, dict):
			shiprocket_data.update(new_data)

		if context:
			history = shiprocket_data.setdefault("history", [])
			history.append(
				{
					"timestamp": frappe.utils.now(),
					"context": context,
					"data": new_data or {},
				}
			)
			shiprocket_data["history"] = history[-50:]
			shiprocket_data["latest"] = new_data or {}

		return existing

	def _validate_shipment_data(self, shipment_doc):
		errors = []
		try:
			pickup = self._get_pickup_address(shipment_doc)
			delivery = frappe.get_doc("Address", shipment_doc.delivery_address_name)
		except Exception:
			frappe.throw(_("Unable to fetch pickup or delivery address"))

		if not getattr(pickup, "address_line1", None):
			errors.append(_("Pickup Address: Address Line 1 is required"))
		if not getattr(pickup, "city", None):
			errors.append(_("Pickup Address: City is required"))
		if not getattr(pickup, "state", None):
			errors.append(_("Pickup Address: State is required"))
		if not getattr(pickup, "pincode", None):
			errors.append(_("Pickup Address: Pincode is required"))
		if not getattr(pickup, "country", None):
			errors.append(_("Pickup Address: Country is required"))

		if not getattr(delivery, "address_line1", None):
			errors.append(_("Delivery Address: Address Line 1 is required"))
		if not getattr(delivery, "city", None):
			errors.append(_("Delivery Address: City is required"))
		if not getattr(delivery, "state", None):
			errors.append(_("Delivery Address: State is required"))
		if not getattr(delivery, "pincode", None):
			errors.append(_("Delivery Address: Pincode is required"))
		if not getattr(delivery, "country", None):
			errors.append(_("Delivery Address: Country is required"))

		pickup_email, pickup_phone = self._get_contact_details(pickup)
		delivery_email, delivery_phone = self._get_contact_details(delivery)
		if not _validate_email(pickup_email):
			errors.append(_("Pickup Address: Valid email is required. Please add email to the address or linked contact"))
		if not _validate_phone(pickup_phone):
			errors.append(_("Pickup Address: Valid phone number is required. Please add phone to the address or linked contact"))
		if not _validate_email(delivery_email):
			errors.append(_("Delivery Address: Valid email is required. Please add email to the address or linked contact"))
		if not _validate_phone(delivery_phone):
			errors.append(_("Delivery Address: Valid phone number is required. Please add phone to the address or linked contact"))

		try:
			value = float(shipment_doc.value_of_goods or 0)
		except Exception:
			value = 0
		if value <= 0:
			errors.append(_("Value of Goods is required and must be greater than 0"))

		parcels = shipment_doc.shipment_parcel or []
		if not parcels:
			errors.append(_("At least one parcel is required"))
		else:
			for idx, parcel in enumerate(parcels):
				p_weight = getattr(parcel, "weight", None) if not isinstance(parcel, dict) else parcel.get("weight")
				p_count = getattr(parcel, "count", None) if not isinstance(parcel, dict) else parcel.get("count")
				try:
					p_weight_val = float(p_weight or 0)
				except Exception:
					p_weight_val = 0
				try:
					p_count_val = int(p_count or 0)
				except Exception:
					p_count_val = 0
				if p_weight_val <= 0:
					errors.append(_("Parcel {0}: Weight is required and must be greater than 0").format(idx + 1))
				if p_count_val <= 0:
					errors.append(_("Parcel {0}: Count is required and must be greater than 0").format(idx + 1))

		if not shipment_doc.pickup_date:
			errors.append(_("Pickup Date is required"))

		if errors:
			error_message = _("<b>Please fix the following errors before creating shipment:</b><br><br>")
			error_message += "<br>".join([f"• {err}" for err in errors])
			frappe.throw(error_message, title=_("Required Fields Missing"))

	def _build_tracking_status_info(self, tracking_data: dict | None) -> str | None:
		"""Keep Shipment.tracking_status_info short; store full payload in extended_provider_data."""
		if not tracking_data:
			return None

		shipment_track = tracking_data.get("shipment_track")
		if isinstance(shipment_track, list) and shipment_track:
			latest = shipment_track[0] or {}
			parts = [
				latest.get("current_status") or latest.get("status"),
				latest.get("current_timestamp") or latest.get("date"),
				latest.get("location") or latest.get("city"),
			]
			summary = " | ".join(str(part).strip() for part in parts if part)
			if summary:
				return summary[:140]

		parts = [
			tracking_data.get("track_status"),
			tracking_data.get("shipment_status"),
			tracking_data.get("etd"),
		]
		summary = " | ".join(str(part).strip() for part in parts if part)
		if summary:
			return summary[:140]

		return frappe.as_json(tracking_data)[:140]

	def _get_settings(self):
		if not frappe.db.exists("DocType", "Shiprocket Settings"):
			return None
		try:
			return frappe.get_single("Shiprocket Settings")
		except Exception:
			return None

	def _is_enabled(self) -> bool:
		settings = self._get_settings()
		return bool(settings and getattr(settings, "enabled", 0))

	def _get_base_url(self) -> str:
		return SHIPROCKET_API_BASE_URL

	def authenticate(self) -> None:
		if not self._is_enabled():
			raise frappe.ValidationError(_("Shiprocket is not enabled."))

		settings = self._get_settings()
		if not settings or not settings.email or not settings.password:
			raise frappe.ValidationError(_("Please configure Shiprocket Settings."))

		site_key = frappe.local.site
		cached = _get_cached_token(site_key)
		if cached:
			return

		payload = {"email": settings.email, "password": settings.get_password("password")}
		response = None
		try:
			response = requests.post(
				url=f"{self._get_base_url()}/auth/login",
				json=payload,
				headers={"Content-Type": "application/json"},
				timeout=30,
			)
			response.raise_for_status()
			resp = response.json()
		except Exception:
			error_detail = None
			try:
				error_detail = (response.json() or {}).get("message")
			except Exception:
				error_detail = getattr(response, "text", None)
			try:
				frappe.log_error(
					message=frappe.as_json(
						{
							"url": f"{self._get_base_url()}/auth/login",
							"status_code": getattr(response, "status_code", None),
							"response_text": getattr(response, "text", None),
							"message": error_detail,
						}
					),
					title="Shiprocket Authentication Failed",
				)
			except Exception:
				frappe.log_error(title="Shiprocket Authentication Failed")
			if error_detail:
				raise frappe.ValidationError(_("Shiprocket authentication failed: {0}").format(error_detail))
			raise frappe.ValidationError(_("Shiprocket authentication failed. Please verify credentials."))

		token = (resp or {}).get("token")
		if not token:
			frappe.log_error(message=frappe.as_json(resp), title="Shiprocket Authentication Failed")
			raise frappe.ValidationError(_("Shiprocket authentication failed. Please verify credentials."))

		expires_at = _decode_jwt_expiry(token)
		_set_cached_token(site_key, _ShiprocketToken(token=token, expires_at=expires_at))

	def _get_auth_headers(self) -> dict[str, str]:
		self.authenticate()
		cached = _get_cached_token(frappe.local.site)
		if not cached:
			raise frappe.ValidationError(_("Shiprocket authentication token is unavailable."))
		token = cached.token
		return {"Authorization": f"Bearer {token}", "Content-Type": "application/json"}

	def _clear_cached_token(self) -> None:
		_clear_cached_token(frappe.local.site)

	def fetch_shipping_rates(self, *, shipment_doc, **kwargs) -> list[dict]:
		if not self._is_enabled():
			return []

		try:
			payload = self._build_serviceability_payload(shipment_doc)
		except Exception:
			frappe.log_error(title="Shiprocket Rate Mapping Failed")
			return []

		response = None
		try:
			response = requests.get(
				url=f"{self._get_base_url()}/courier/serviceability/",
				params=payload,
				headers=self._get_auth_headers(),
				timeout=30,
			)
			if response.status_code == 401:
				self._clear_cached_token()
				response = requests.get(
					url=f"{self._get_base_url()}/courier/serviceability/",
					params=payload,
					headers=self._get_auth_headers(),
					timeout=30,
				)
			response.raise_for_status()
			resp = response.json()
		except Exception as e:
			try:
				frappe.log_error(
					message=frappe.as_json(
						{
							"url": f"{self._get_base_url()}/courier/serviceability/",
							"payload": payload,
							"status_code": getattr(response, "status_code", None),
							"response_text": getattr(response, "text", None),
							"error": str(e),
						}
					),
					title="Shiprocket Rate Fetch Failed",
				)
			except Exception:
				frappe.log_error(message=str(e), title="Shiprocket Rate Fetch Failed")
			return []

		couriers = ((resp or {}).get("data") or {}).get("available_courier_companies") or []
		out = []
		for c in couriers:
			try:
				out.append(
					{
						"service_provider": self.provider_name,
						"carrier": c.get("courier_company_name"),
						"service_name": c.get("courier_name") or c.get("courier_company_name"),
						"carrier_service": c.get("courier_company_name"),
						"total_price": c.get("rate"),
						"currency": "INR",
						"shiprocket": {
							"courier_company_id": c.get("courier_company_id"),
							"estimated_delivery_days": c.get("estimated_delivery_days"),
							"etd": c.get("etd"),
							"cod": c.get("cod"),
						},
					}
				)
			except Exception:
				continue

		return out

	def create_shipment(self, *, shipment_doc, service_info: dict, **kwargs) -> dict:
		if not self._is_enabled():
			raise frappe.ValidationError(_("Shiprocket is not enabled."))

		# Validate required fields BEFORE making API call
		self._validate_shipment_data(shipment_doc)

		payload = self._build_create_order_payload(shipment_doc, service_info=service_info)
		try:
			response = requests.post(
				url=f"{self._get_base_url()}/orders/create/adhoc",
				json=payload,
				headers=self._get_auth_headers(),
				timeout=30,
			)
			response.raise_for_status()
			resp = response.json()
		except requests.exceptions.HTTPError as e:
			# Log the actual error response from Shiprocket
			error_detail = ""
			try:
				error_resp = e.response.json()
				error_detail = frappe.as_json(error_resp, indent=2)
				# Try to extract specific error message
				if isinstance(error_resp, dict):
					if 'message' in error_resp:
						error_detail = error_resp['message']
					elif 'errors' in error_resp:
						error_detail = str(error_resp['errors'])
			except:
				error_detail = e.response.text
			
			frappe.log_error(
				message=f"Payload: {frappe.as_json(payload, indent=2)}\n\nResponse: {error_detail}",
				title="Shiprocket Create Shipment Failed"
			)
			raise frappe.ValidationError(
				_("Shiprocket API Error: {0}").format(error_detail)
			)
		except Exception as e:
			frappe.log_error(
				message=f"Payload: {frappe.as_json(payload, indent=2)}\n\nError: {str(e)}",
				title="Shiprocket Create Shipment Failed"
			)
			raise frappe.ValidationError(_("Unable to create Shiprocket shipment: {0}").format(str(e)))

		order_id = (resp or {}).get("order_id")
		shipment_id = (resp or {}).get("shipment_id")
		awb = (resp or {}).get("awb_code")
		if not (order_id and shipment_id):
			frappe.log_error(message=frappe.as_json(resp), title="Shiprocket Create Shipment Failed")
			raise frappe.ValidationError(_("Shiprocket shipment creation failed. Please check Error Log."))

		# Keep the fresh remote identifiers available for follow-up calls in the same request.
		shipment_doc.shiprocket_order_id = str(order_id)
		shipment_doc.shiprocket_shipment_id = str(shipment_id)

		# CRITICAL: Generate AWB if not automatically assigned
		if not awb and shipment_id:
			frappe.msgprint(_("Order created. Generating AWB..."))
			awb = self._generate_awb(shipment_id, service_info, shipment_doc=shipment_doc)
			if not awb:
				# If Shiprocket has already cancelled the order, we auto-cancel ERP shipment inside _generate_awb.
				if shipment_doc.status == "Cancelled":
					frappe.msgprint(
						_(
							"Shiprocket has this order in cancelled state, so AWB generation cannot continue. "
							"The shipment has been marked Cancelled in ERPNext."
						),
						alert=True,
					)
				else:
					frappe.msgprint(
						_("⚠️ AWB generation pending. You can sync it later using 'Sync AWB' button."),
						alert=True,
					)

		return {
			"service_provider": self.provider_name,
			"carrier": service_info.get("carrier") or self.provider_name,
			"carrier_service": service_info.get("carrier_service") or service_info.get("service_name"),
			"shipment_id": str(shipment_id),
			"shipment_amount": service_info.get("total_price"),
			"awb_number": awb or "",
			"status": shipment_doc.status if shipment_doc.status == "Cancelled" else "Booked",
			"shiprocket_order_id": str(order_id),
			"shiprocket_shipment_id": str(shipment_id),
			"extended_provider_data": self._update_extended_data(
				shipment_doc,
				resp,
				context="create shipment",
			),
		}

	def _generate_awb(self, shipment_id, service_info, shipment_doc=None):
		"""
		Generate AWB for a shipment
		API: POST /courier/assign/awb
		"""
		try:
			courier_id = service_info.get("shiprocket", {}).get("courier_company_id")
			
			if not courier_id:
				frappe.logger().warning(f"No courier_company_id found for shipment {shipment_id}")
				return None

			order_id = getattr(shipment_doc, "shiprocket_order_id", None) if shipment_doc else None
			if order_id:
				order_data = self._fetch_order_details(order_id)
				if order_data:
					order_status = self._sync_remote_order_state(
						shipment_doc,
						order_data,
						context="before AWB generation",
					) or self._extract_remote_order_status(order_data)
					if "cancel" in str(order_status).lower():
						frappe.logger().warning(
							f"Order {order_id} is cancelled. Cannot generate AWB. Status: {order_status}"
						)
						return None
			
			payload = {
				"shipment_id": int(shipment_id),
				"courier_id": int(courier_id)
			}
			
			url = f"{self._get_base_url()}/courier/assign/awb"
			response = requests.post(
				url=url,
				json=payload,
				headers=self._get_auth_headers(),
				timeout=30
			)
			response.raise_for_status()
			result = response.json()
			
			# Check response
			if result.get("awb_assign_status") == 1:
				awb_code = result.get("response", {}).get("data", {}).get("awb_code")
				if awb_code:
					frappe.msgprint(_("✓ AWB Generated: {0}").format(awb_code), alert=True, indicator="green")
					return awb_code
			
			# Log if AWB not generated
			frappe.log_error(
				message=frappe.as_json(result, indent=2),
				title="Shiprocket AWB Generation Response"
			)
			return None
			
		except requests.exceptions.HTTPError as e:
			error_detail = ""
			try:
				error_resp = e.response.json()
				error_detail = error_resp.get("message", str(error_resp))
			except:
				error_detail = e.response.text

			# Option A: auto-cancel ERP Shipment when Shiprocket says order is cancelled.
			# Shiprocket commonly returns: "order is in cancelled state."
			if shipment_doc and "cancel" in (error_detail or "").lower():
				try:
					provider_data = self._update_extended_data(
						shipment_doc,
						{
							"last_awb_error": {
						"shipment_id": shipment_id,
						"courier_id": courier_id,
						"status_code": getattr(getattr(e, "response", None), "status_code", None),
						"response_text": getattr(getattr(e, "response", None), "text", None),
						"message": error_detail,
							}
						},
						context="awb generation failed",
					)
					shipment_doc.db_set(
						{
							"status": "Cancelled",
							"extended_provider_data": frappe.as_json(provider_data),
						},
					)
				except Exception:
					# Never block the original flow because of a best-effort status update
					frappe.log_error(title="Shiprocket Cancelled State Handling Failed")
			
			frappe.log_error(
				message=(
					f"Shipment ID: {shipment_id}\n"
					f"Courier ID: {courier_id}\n"
					f"Status Code: {getattr(getattr(e, 'response', None), 'status_code', None)}\n"
					f"Response: {getattr(getattr(e, 'response', None), 'text', None)}\n"
					f"Error: {error_detail}"
				),
				title="Shiprocket AWB Generation Failed"
			)
			return None
		except Exception as e:
			frappe.log_error(
				message=f"Shipment ID: {shipment_id}\nError: {str(e)}",
				title="Shiprocket AWB Generation Error"
			)
			return None

	def sync_awb_from_shiprocket(self, shipment_doc):
		"""Fetch AWB from Shiprocket if not assigned yet"""
		if shipment_doc.awb_number:
			return shipment_doc.awb_number
		
		order_id = shipment_doc.shiprocket_order_id
		if not order_id:
			frappe.msgprint(_("Shiprocket Order ID not found. Cannot sync AWB."))
			return None
		
		response = None
		try:
			order_data = self._fetch_order_details(order_id) or {}
			awb = order_data.get("awb_code")
			shipments = order_data.get("shipments")
			shipment_id = None
			if isinstance(shipments, list) and shipments:
				shipment_id = (shipments[0] or {}).get("id")
			
			if awb:
				shipment_doc.awb_number = awb
				if shipment_id and not shipment_doc.shiprocket_shipment_id:
					shipment_doc.shiprocket_shipment_id = str(shipment_id)
				shipment_doc.save()
				frappe.db.commit()
				frappe.msgprint(_("AWB synced from Shiprocket: {0}").format(awb))
				return awb
			else:
				status = self._sync_remote_order_state(
					shipment_doc, order_data, context="during AWB sync"
				) or order_data.get("status", "Unknown")
				if "cancel" in str(status).lower():
					frappe.msgprint(
						_(
							"Shiprocket order is in cancelled state, so AWB cannot be assigned. "
							"ERPNext shipment status has been updated."
						)
					)
				else:
					frappe.msgprint(
						_(
							"AWB not yet assigned by courier. Current status: {0}. Please wait and try again."
						).format(status)
					)
				return None
		except Exception as e:
			frappe.log_error(
				message=frappe.as_json(
					{
						"shipment": getattr(shipment_doc, "name", None),
						"order_id": order_id,
						"status_code": getattr(response, "status_code", None),
						"response_text": getattr(response, "text", None),
						"error": str(e),
					}
				),
				title="Shiprocket AWB Sync Failed",
			)
			frappe.msgprint(_("Unable to sync AWB from Shiprocket. Please try again later."))
			return None

	def get_label(self, *, shipment_doc, **kwargs):
		# Try to sync AWB if missing
		if not shipment_doc.awb_number:
			frappe.msgprint(_("AWB not found. Attempting to sync from Shiprocket..."))
			awb = self.sync_awb_from_shiprocket(shipment_doc)
			if not awb:
				# If the shipment got auto-cancelled (Option A), be explicit.
				if shipment_doc.status == "Cancelled":
					frappe.throw(
						_(
							"Shiprocket has this order in cancelled state, so AWB is not available and label cannot be generated. "
							"Please recreate the shipment."
						)
					)
				frappe.throw(
					_(
						"AWB number is required to generate label. The courier may not have assigned it yet. "
						"Please wait a few minutes and try again."
					)
				)
		
		shipment_id = shipment_doc.shiprocket_shipment_id or shipment_doc.shipment_id
		if not shipment_id:
			raise frappe.ValidationError(_("Missing Shiprocket shipment id."))

		payload = {"shipment_id": [int(shipment_id)]}
		try:
			response = requests.post(
				url=f"{self._get_base_url()}/courier/generate/label",
				json=payload,
				headers=self._get_auth_headers(),
				timeout=30,
			)
			response.raise_for_status()
			resp = response.json()
		except requests.exceptions.HTTPError as e:
			# Get detailed error from Shiprocket
			error_detail = ""
			try:
				error_resp = e.response.json()
				if isinstance(error_resp, dict):
					error_detail = error_resp.get("message", str(error_resp))
				else:
					error_detail = str(error_resp)
			except:
				error_detail = e.response.text
			
			frappe.log_error(
				message=f"Shipment ID: {shipment_id}\nResponse: {error_detail}",
				title="Shiprocket Label Generation Failed"
			)
			
			# Check if AWB issue
			if "awb not found" in error_detail.lower() or "not_created" in error_detail.lower():
				frappe.throw(_("AWB not assigned yet. Please wait a few minutes for the courier to assign an AWB, then try again."))
			elif "cancelled" in error_detail.lower():
				frappe.throw(_("Shiprocket order is in cancelled state. Please recreate the shipment."))
			else:
				frappe.throw(_("Shiprocket API Error: {0}").format(error_detail))
		except Exception as e:
			frappe.log_error(message=str(e), title="Shiprocket Label Generation Failed")
			raise frappe.ValidationError(_("Unable to generate Shiprocket label: {0}").format(str(e)))

		label_url = ((resp or {}).get("label_url") or (resp or {}).get("label_created"))
		if not label_url:
			frappe.log_error(message=frappe.as_json(resp), title="Shiprocket Label Generation Failed")
			raise frappe.ValidationError(_("Shiprocket label generation failed. Please check Error Log."))

		try:
			content = frappe.utils.file_manager.get_file(label_url)[1]  # may not work for external urls
		except Exception:
			content = None

		if content:
			return content

		# Fallback: return label_url and let caller download.
		return label_url

	def update_tracking(self, *, shipment_doc, **kwargs) -> dict | None:
		awb = shipment_doc.awb_number
		if not awb:
			return None

		try:
			response = requests.get(
				url=f"{self._get_base_url()}/courier/track/awb/{awb}",
				headers=self._get_auth_headers(),
				timeout=30,
			)
			response.raise_for_status()
			resp = response.json()
		except Exception:
			frappe.log_error(title="Shiprocket Tracking Failed")
			return None

		data = (resp or {}).get("tracking_data") or {}
		track = data.get("track_status")
		track_url = data.get("shipment_track") or ""
		return {
			"awb_number": awb,
			"tracking_status": str(track) if track is not None else None,
			"tracking_status_info": self._build_tracking_status_info(data),
			"tracking_url": track_url if isinstance(track_url, str) else frappe.as_json(track_url),
			"extended_provider_data": self._update_extended_data(
				shipment_doc,
				resp,
				context="tracking update",
			),
		}

	def cancel_shipment(self, *, shipment_doc, **kwargs) -> dict | None:
		"""Cancel shipment on Shiprocket"""
		order_id = shipment_doc.shiprocket_order_id
		if not order_id:
			frappe.msgprint(_("Shiprocket Order ID not found. Cannot cancel on Shiprocket."), alert=True)
			return None

		payload = {"ids": [int(order_id)]}
		try:
			response = requests.post(
				url=f"{self._get_base_url()}/orders/cancel",
				json=payload,
				headers=self._get_auth_headers(),
				timeout=30,
			)
			response.raise_for_status()
			resp = response.json()
			
			# Check if cancellation was successful
			message = str(resp.get("message") or "").strip().rstrip(".")
			if message.lower() == "order cancelled successfully":
				frappe.logger().info(f"Shiprocket order {order_id} cancelled successfully")
				return {
					"status": "success",
					"extended_provider_data": self._update_extended_data(
						shipment_doc,
						{"cancel_response": resp},
						context="cancel shipment",
					),
				}
			else:
				frappe.log_error(
					message=frappe.as_json(resp, indent=2),
					title="Shiprocket Cancel Response"
				)
				return {
					"status": "unknown",
					"extended_provider_data": self._update_extended_data(
						shipment_doc,
						{"cancel_response": resp},
						context="cancel shipment",
					),
				}
				
		except requests.exceptions.HTTPError as e:
			error_detail = ""
			try:
				error_resp = e.response.json()
				error_detail = error_resp.get("message", str(error_resp))
			except:
				error_detail = e.response.text
			
			frappe.log_error(
				message=f"Order ID: {order_id}\nError: {error_detail}",
				title="Shiprocket Cancel Failed"
			)
			frappe.msgprint(
				_("Shiprocket cancellation failed: {0}").format(error_detail),
				alert=True,
				indicator='red'
			)
			return None
		except Exception as e:
			frappe.log_error(
				message=f"Order ID: {order_id}\nError: {str(e)}",
				title="Shiprocket Cancel Error"
			)
			return None

	def _build_serviceability_payload(self, shipment_doc) -> dict:
		pickup = self._get_pickup_address(shipment_doc)
		delivery = frappe.get_doc("Address", shipment_doc.delivery_address_name)

		parcels = shipment_doc.shipment_parcel or []
		if parcels:
			if isinstance(parcels[0], dict):
				# Parcels are dicts - use .get()
				weight = sum([float(p.get('weight') or 0) for p in parcels]) or 0.5
			else:
				# Parcels are objects - use getattr()
				weight = sum([float(getattr(p, 'weight', 0) or 0) for p in parcels]) or 0.5
		else:
			# Fallback to shipment total_weight
			if isinstance(shipment_doc, dict):
				weight = float(shipment_doc.get('total_weight') or 0) or 0.5
			else:
				weight = float(getattr(shipment_doc, 'total_weight', 0) or 0) or 0.5

		cod = 1 if (shipment_doc.get("payment_type") == "Cash" or shipment_doc.get("is_cod")) else 0

		return {
			"pickup_postcode": (pickup.pincode or "").replace(" ", ""),
			"delivery_postcode": (delivery.pincode or "").replace(" ", ""),
			"weight": weight,
			"cod": cod,
		}

	def _get_contact_details(self, address):
		"""Get email and phone from address or linked contacts"""
		email = ""
		phone = ""
		
		# Try to get from address email/phone fields
		if hasattr(address, 'email_id') and address.email_id:
			email = address.email_id
		if hasattr(address, 'phone') and address.phone:
			phone = address.phone
		
		# Try to get from linked contacts
		if not email or not phone:
			links = frappe.get_all("Dynamic Link", 
				filters={
					"link_doctype": "Address",
					"link_name": address.name,
					"parenttype": "Contact"
				},
				fields=["parent"]
			)
			
			for link in links:
				try:
					contact = frappe.get_doc("Contact", link.parent)
					if not email and contact.email_id:
						email = contact.email_id
					if not phone and contact.phone:
						phone = contact.phone
					if email and phone:
						break
				except:
					continue
		
		# Return what we found (empty if nothing found)
		return email or "", phone or ""

	def _build_create_order_payload(self, shipment_doc, service_info: dict) -> dict:
		pickup = self._get_pickup_address(shipment_doc)
		delivery = frappe.get_doc("Address", shipment_doc.delivery_address_name)

		# Get contact details (already validated in _validate_shipment_data)
		pickup_email, pickup_phone = self._get_contact_details(pickup)
		delivery_email, delivery_phone = self._get_contact_details(delivery)

		items = []
		for row in shipment_doc.shipment_parcel or []:
			items.append(
				{
					"name": row.get("description") or shipment_doc.description_of_content or shipment_doc.name,
					"sku": row.get("item_code") or shipment_doc.name,
					"units": int(row.get("count") or 1),
					"selling_price": float(shipment_doc.value_of_goods or 0),
					"discount": 0,
					"tax": 0,
					"hsn": row.get("hsn_code") or "",
				}
			)

		if not items:
			items = [
				{
					"name": shipment_doc.description_of_content or shipment_doc.name,
					"sku": shipment_doc.name,
					"units": 1,
					"selling_price": float(shipment_doc.value_of_goods or 0),
					"discount": 0,
					"tax": 0,
					"hsn": "",
				}
			]

		parcels = shipment_doc.shipment_parcel or []
		length = max([(p.length or 0) for p in parcels] or [0]) or 10
		breadth = max([(p.width or 0) for p in parcels] or [0]) or 10
		height = max([(p.height or 0) for p in parcels] or [0]) or 10
		weight = sum([(p.weight or 0) for p in parcels]) or (shipment_doc.total_weight or 0) or 0.5

		is_cod = 1 if (shipment_doc.get("payment_type") == "Cash" or shipment_doc.get("is_cod")) else 0
		cod_amount = float(shipment_doc.value_of_goods or 0) if is_cod else 0

		payload = {
			"order_id": shipment_doc.name,
			"order_date": str(shipment_doc.pickup_date or frappe.utils.nowdate()),
			"pickup_location": pickup.address_title or "Primary",
			"billing_customer_name": shipment_doc.pickup_contact_name or pickup.address_title or "Sender",
			"billing_last_name": "",
			"billing_address": " ".join(filter(None, [pickup.address_line1, pickup.address_line2])),
			"billing_city": pickup.city,
			"billing_pincode": (pickup.pincode or "").replace(" ", ""),
			"billing_state": pickup.state,
			"billing_country": pickup.country,
			"billing_email": pickup_email,
			"billing_phone": pickup_phone,
			"shipping_is_billing": False,
			"shipping_customer_name": shipment_doc.delivery_contact_name or delivery.address_title or "Recipient",
			"shipping_last_name": "",
			"shipping_address": " ".join(filter(None, [delivery.address_line1, delivery.address_line2])),
			"shipping_city": delivery.city,
			"shipping_pincode": (delivery.pincode or "").replace(" ", ""),
			"shipping_state": delivery.state,
			"shipping_country": delivery.country,
			"shipping_email": delivery_email,
			"shipping_phone": delivery_phone,
			"order_items": items,
			"payment_method": "COD" if is_cod else "Prepaid",
			"sub_total": float(shipment_doc.value_of_goods or 0),
			"length": length,
			"breadth": breadth,
			"height": height,
			"weight": weight,
			"cod": is_cod,
			"cod_amount": cod_amount,
		}

		courier_company_id = ((service_info.get("shiprocket") or {}).get("courier_company_id"))
		if courier_company_id:
			payload["courier_company_id"] = int(courier_company_id)

		return payload
