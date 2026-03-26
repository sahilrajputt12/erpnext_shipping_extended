from __future__ import annotations

import json
import threading
from dataclasses import dataclass

import frappe
from frappe import _
import requests

from .base_provider import BaseShippingProvider


SHIPROCKET_API_BASE_URL = "https://apiv2.shiprocket.in/v1/external"


@dataclass(frozen=True)
class _ShiprocketToken:
	token: str


_token_lock = threading.Lock()
_token_cache: dict[str, _ShiprocketToken] = {}


class ShiprocketProvider(BaseShippingProvider):
	provider_name = "Shiprocket"

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
		with _token_lock:
			if site_key in _token_cache:
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

		with _token_lock:
			_token_cache[site_key] = _ShiprocketToken(token=token)

	def _get_auth_headers(self) -> dict[str, str]:
		self.authenticate()
		with _token_lock:
			token = _token_cache[frappe.local.site].token
		return {"Authorization": f"Bearer {token}", "Content-Type": "application/json"}

	def _clear_cached_token(self) -> None:
		with _token_lock:
			_token_cache.pop(frappe.local.site, None)

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
		except Exception:
			try:
				frappe.log_error(
					message=frappe.as_json(
						{
							"url": f"{self._get_base_url()}/courier/serviceability/",
							"payload": payload,
							"status_code": getattr(response, "status_code", None),
							"response_text": getattr(response, "text", None),
						}
					),
					title="Shiprocket Rate Fetch Failed",
				)
			except Exception:
				frappe.log_error(title="Shiprocket Rate Fetch Failed")
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

		# CRITICAL: Generate AWB if not automatically assigned
		if not awb and shipment_id:
			frappe.msgprint(_("Order created. Generating AWB..."))
			awb = self._generate_awb(shipment_id, service_info)
			if not awb:
				frappe.msgprint(_("⚠️ AWB generation pending. You can sync it later using 'Sync AWB' button."), alert=True)

		return {
			"service_provider": self.provider_name,
			"carrier": service_info.get("carrier") or self.provider_name,
			"carrier_service": service_info.get("carrier_service") or service_info.get("service_name"),
			"shipment_id": str(shipment_id),
			"shipment_amount": service_info.get("total_price"),
			"awb_number": awb or "",
			"shiprocket_order_id": str(order_id),
			"shiprocket_shipment_id": str(shipment_id),
			"extended_provider_data": {"shiprocket": resp},
		}

	def _generate_awb(self, shipment_id, service_info):
		"""
		Generate AWB for a shipment
		API: POST /courier/assign/awb
		"""
		try:
			courier_id = service_info.get("shiprocket", {}).get("courier_company_id")
			
			if not courier_id:
				frappe.logger().warning(f"No courier_company_id found for shipment {shipment_id}")
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
			
			frappe.log_error(
				message=f"Shipment ID: {shipment_id}\nCourier ID: {courier_id}\nError: {error_detail}",
				title="Shiprocket AWB Generation Failed"
			)
			return None
		except Exception as e:
			frappe.log_error(
				message=f"Shipment ID: {shipment_id}\nError: {str(e)}",
				title="Shiprocket AWB Generation Error"
			)
			return None

	def _validate_shipment_data(self, shipment_doc):
		"""Validate all required fields before creating shipment"""
		errors = []
		
		# Get addresses
		try:
			pickup = frappe.get_doc("Address", shipment_doc.pickup_address_name)
			delivery = frappe.get_doc("Address", shipment_doc.delivery_address_name)
		except:
			frappe.throw(_("Unable to fetch pickup or delivery address"))
		
		# Validate Pickup Address
		if not pickup.address_line1:
			errors.append(_("Pickup Address: Address Line 1 is required"))
		if not pickup.city:
			errors.append(_("Pickup Address: City is required"))
		if not pickup.state:
			errors.append(_("Pickup Address: State is required"))
		if not pickup.pincode:
			errors.append(_("Pickup Address: Pincode is required"))
		if not pickup.country:
			errors.append(_("Pickup Address: Country is required"))
		
		# Validate Delivery Address
		if not delivery.address_line1:
			errors.append(_("Delivery Address: Address Line 1 is required"))
		if not delivery.city:
			errors.append(_("Delivery Address: City is required"))
		if not delivery.state:
			errors.append(_("Delivery Address: State is required"))
		if not delivery.pincode:
			errors.append(_("Delivery Address: Pincode is required"))
		if not delivery.country:
			errors.append(_("Delivery Address: Country is required"))
		
		# Get contact details
		pickup_email, pickup_phone = self._get_contact_details(pickup)
		delivery_email, delivery_phone = self._get_contact_details(delivery)
		
		# Validate contact details (don't accept defaults)
		if not pickup_email or pickup_email == "noreply@example.com":
			errors.append(_("Pickup Address: Email is required. Please add email to the address or linked contact"))
		if not pickup_phone or pickup_phone == "9999999999":
			errors.append(_("Pickup Address: Phone number is required. Please add phone to the address or linked contact"))
		
		if not delivery_email or delivery_email == "noreply@example.com":
			errors.append(_("Delivery Address: Email is required. Please add email to the address or linked contact"))
		if not delivery_phone or delivery_phone == "9999999999":
			errors.append(_("Delivery Address: Phone number is required. Please add phone to the address or linked contact"))
		
		# Validate shipment details
		if not shipment_doc.value_of_goods or float(shipment_doc.value_of_goods) <= 0:
			errors.append(_("Value of Goods is required and must be greater than 0"))
		
		if not shipment_doc.shipment_parcel or len(shipment_doc.shipment_parcel) == 0:
			errors.append(_("At least one parcel is required"))
		else:
			for idx, parcel in enumerate(shipment_doc.shipment_parcel):
				if not parcel.weight or float(parcel.weight) <= 0:
					errors.append(_("Parcel {0}: Weight is required and must be greater than 0").format(idx + 1))
				if not parcel.count or int(parcel.count) <= 0:
					errors.append(_("Parcel {0}: Count is required and must be greater than 0").format(idx + 1))
		
		if not shipment_doc.pickup_date:
			errors.append(_("Pickup Date is required"))
		
		# If there are errors, show them all at once
		if errors:
			error_message = _("<b>Please fix the following errors before creating shipment:</b><br><br>")
			error_message += "<br>".join([f"• {err}" for err in errors])
			frappe.throw(error_message, title=_("Required Fields Missing"))

	def sync_awb_from_shiprocket(self, shipment_doc):
		"""Fetch AWB from Shiprocket if not assigned yet"""
		if shipment_doc.awb_number:
			return shipment_doc.awb_number
		
		order_id = shipment_doc.shiprocket_order_id
		if not order_id:
			frappe.msgprint(_("Shiprocket Order ID not found. Cannot sync AWB."))
			return None
		
		try:
			url = f"{self._get_base_url()}/orders/show/{order_id}"
			response = requests.get(url, headers=self._get_auth_headers(), timeout=30)
			response.raise_for_status()
			result = response.json()
			
			order_data = result.get("data", {})
			awb = order_data.get("awb_code")
			shipment_id = order_data.get("shipments", [{}])[0].get("id") if order_data.get("shipments") else None
			
			if awb:
				shipment_doc.awb_number = awb
				if shipment_id and not shipment_doc.shiprocket_shipment_id:
					shipment_doc.shiprocket_shipment_id = str(shipment_id)
				shipment_doc.save()
				frappe.db.commit()
				frappe.msgprint(_("AWB synced from Shiprocket: {0}").format(awb))
				return awb
			else:
				status = order_data.get("status", "Unknown")
				frappe.msgprint(_("AWB not yet assigned by courier. Current status: {0}. Please wait and try again.").format(status))
				return None
		except Exception as e:
			frappe.log_error(message=str(e), title="Shiprocket AWB Sync Failed")
			frappe.msgprint(_("Unable to sync AWB from Shiprocket. Please try again later."))
			return None

	def get_label(self, *, shipment_doc, **kwargs):
		# Try to sync AWB if missing
		if not shipment_doc.awb_number:
			frappe.msgprint(_("AWB not found. Attempting to sync from Shiprocket..."))
			awb = self.sync_awb_from_shiprocket(shipment_doc)
			if not awb:
				frappe.throw(_("AWB number is required to generate label. The courier may not have assigned it yet. Please wait a few minutes and try again."))
		
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
			"extended_provider_data": {"shiprocket": resp},
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
			if resp.get("message") == "Order cancelled successfully":
				frappe.logger().info(f"Shiprocket order {order_id} cancelled successfully")
				return {"status": "success", "extended_provider_data": {"shiprocket": resp}}
			else:
				frappe.log_error(
					message=frappe.as_json(resp, indent=2),
					title="Shiprocket Cancel Response"
				)
				return {"status": "unknown", "extended_provider_data": {"shiprocket": resp}}
				
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
		pickup = frappe.get_doc("Address", shipment_doc.pickup_address_name)
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
		pickup = frappe.get_doc("Address", shipment_doc.pickup_address_name)
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
