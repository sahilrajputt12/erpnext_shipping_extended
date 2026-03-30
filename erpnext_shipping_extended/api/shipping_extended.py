from __future__ import annotations

import json

import frappe
from frappe import _


def _safe_call_original(method_path: str, *, kwargs: dict):
	"""Call original erpnext_shipping implementation even when we override it via hooks."""
	try:
		from frappe.modules.utils import get_module_path

		# try to import the module and call function directly
		module_path, fn_name = method_path.rsplit(".", 1)
		mod = frappe.get_module(module_path)
		fn = getattr(mod, fn_name)
		return fn(**kwargs)
	except Exception:
		frappe.log_error(title="ERPNext Shipping Extended: Original Method Call Failed")
		return None


def _get_shiprocket_provider():
	from erpnext_shipping_extended.providers import get_provider

	try:
		return get_provider("Shiprocket")
	except Exception:
		return None


def _merge_extended_provider_data(doc, incoming_data):
	try:
		existing = json.loads(getattr(doc, "extended_provider_data", None) or "{}")
	except Exception:
		existing = {}

	if not isinstance(existing, dict):
		existing = {}

	if isinstance(incoming_data, str):
		try:
			incoming_data = json.loads(incoming_data)
		except Exception:
			incoming_data = {}

	if not isinstance(incoming_data, dict):
		incoming_data = {}

	for provider_key, payload in incoming_data.items():
		if isinstance(payload, dict) and isinstance(existing.get(provider_key), dict):
			existing[provider_key].update(payload)
		else:
			existing[provider_key] = payload

	return frappe.as_json(existing)


@frappe.whitelist()
def fetch_shipping_rates(
	pickup_from_type,
	delivery_to_type,
	pickup_address_name,
	delivery_address_name,
	parcels,
	description_of_content,
	pickup_date,
	value_of_goods,
	pickup_contact_name=None,
	delivery_contact_name=None,
):
	"""Extend erpnext_shipping rates with Shiprocket rates.

	If erpnext_shipping is missing, returns Shiprocket-only.	
	"""
	args = {
		"pickup_from_type": pickup_from_type,
		"delivery_to_type": delivery_to_type,
		"pickup_address_name": pickup_address_name,
		"delivery_address_name": delivery_address_name,
		"parcels": parcels,
		"description_of_content": description_of_content,
		"pickup_date": pickup_date,
		"value_of_goods": value_of_goods,
		"pickup_contact_name": pickup_contact_name,
		"delivery_contact_name": delivery_contact_name,
	}

	# Base providers (LetMeShip/Sendcloud/etc.)
	base_rates = []
	try:
		import erpnext_shipping  # noqa: F401

		from erpnext_shipping.erpnext_shipping.shipping import fetch_shipping_rates as base_fetch

		base_rates = base_fetch(**args) or []
	except Exception:
		base_rates = []

	# Shiprocket
	shiprocket_rates = []
	try:
		shipment_doc = frappe._dict(
			{
				"pickup_address_name": pickup_address_name,
				"delivery_address_name": delivery_address_name,
				"shipment_parcel": json.loads(parcels) if isinstance(parcels, str) else parcels,
				"description_of_content": description_of_content,
				"pickup_date": pickup_date,
				"value_of_goods": value_of_goods,
				"pickup_from_type": pickup_from_type,
				"delivery_to_type": delivery_to_type,
				"pickup_contact_name": pickup_contact_name,
				"delivery_contact_name": delivery_contact_name,
			}
		)
		provider = _get_shiprocket_provider()
		if provider:
			shiprocket_rates = provider.fetch_shipping_rates(shipment_doc=shipment_doc) or []
	except Exception as e:
		frappe.log_error(message=str(e), title="Shiprocket Rate Fetch Failed")
		shiprocket_rates = []

	# Keep rate dict shape consistent with `erpnext_shipping` so preferred-service logic works.
	# (LetMeShip/SendCloud already run this mapping; Shiprocket was missing.)
	try:
		import erpnext_shipping  # noqa: F401

		from erpnext_shipping.erpnext_shipping.utils import match_parcel_service_type_carrier

		shiprocket_rates = match_parcel_service_type_carrier(
			shiprocket_rates, carrier_fieldname="carrier", service_fieldname="service_name"
		)
	except Exception:
		# Preferred services are optional; never block rate fetching if mapping fails.
		pass

	rates = (base_rates or []) + (shiprocket_rates or [])
	rates = [r for r in rates if isinstance(r, dict) and r.get("total_price") is not None]
	try:
		rates = sorted(rates, key=lambda r: r.get("total_price") or 0)
	except Exception:
		pass
	return rates


@frappe.whitelist()
def create_shipment(
	shipment,
	pickup_from_type,
	delivery_to_type,
	pickup_address_name,
	delivery_address_name,
	shipment_parcel,
	description_of_content,
	pickup_date,
	value_of_goods,
	service_data,
	shipment_notific_email=None,
	tracking_notific_email=None,
	pickup_contact_name=None,
	delivery_contact_name=None,
	delivery_notes=None,
):
	service_info = json.loads(service_data) if isinstance(service_data, str) else service_data

	# Delegate to base erpnext_shipping for non-Shiprocket
	if (service_info or {}).get("service_provider") != "Shiprocket":
		try:
			from erpnext_shipping.erpnext_shipping.shipping import create_shipment as base_create

			return base_create(
				shipment=shipment,
				pickup_from_type=pickup_from_type,
				delivery_to_type=delivery_to_type,
				pickup_address_name=pickup_address_name,
				delivery_address_name=delivery_address_name,
				shipment_parcel=shipment_parcel,
				description_of_content=description_of_content,
				pickup_date=pickup_date,
				value_of_goods=value_of_goods,
				service_data=json.dumps(service_info),
				shipment_notific_email=shipment_notific_email,
				tracking_notific_email=tracking_notific_email,
				pickup_contact_name=pickup_contact_name,
				delivery_contact_name=delivery_contact_name,
				delivery_notes=delivery_notes,
			)
		except Exception:
			frappe.log_error(title="Create Shipment Failed")
			frappe.throw(_("Unable to create shipment."))

	shipment_doc = frappe.get_doc("Shipment", shipment)
	provider = _get_shiprocket_provider()
	if not provider:
		frappe.throw(_("Shiprocket provider not available."))

	try:
		shipment_info = provider.create_shipment(shipment_doc=shipment_doc, service_info=service_info) or {}
	except frappe.ValidationError:
		raise
	except Exception:
		frappe.log_error(title="Shiprocket Create Shipment Failed")
		frappe.throw(_("Unable to create Shiprocket shipment. Please check Error Log."))

	try:
		shipment_doc.db_set(
			{
				"service_provider": shipment_info.get("service_provider"),
				"carrier": shipment_info.get("carrier"),
				"carrier_service": shipment_info.get("carrier_service"),
				"shipment_id": shipment_info.get("shipment_id"),
				"shipment_amount": shipment_info.get("shipment_amount"),
				"awb_number": shipment_info.get("awb_number"),
				"shiprocket_shipment_id": shipment_info.get("shiprocket_shipment_id"),
				"shiprocket_order_id": shipment_info.get("shiprocket_order_id"),
				"extended_provider_data": _merge_extended_provider_data(
					shipment_doc, shipment_info.get("extended_provider_data")
				),
				"status": shipment_info.get("status") or "Booked",
			}
		)
	except Exception:
		frappe.log_error(title="Shiprocket Shipment DB Update Failed")

	return shipment_info


@frappe.whitelist()
def print_shipping_label(shipment: str):
	shipment_doc = frappe.get_doc("Shipment", shipment)
	if shipment_doc.service_provider != "Shiprocket":
		from erpnext_shipping.erpnext_shipping.shipping import print_shipping_label as base_print

		return base_print(shipment)

	provider = _get_shiprocket_provider()
	if not provider:
		frappe.throw(_("Shiprocket provider not available."))

	try:
		label = provider.get_label(shipment_doc=shipment_doc)
	except frappe.ValidationError:
		raise
	except Exception:
		frappe.log_error(title="Shiprocket Label Failed")
		frappe.throw(_("Unable to generate Shiprocket label. Please check Error Log."))

	# If we got bytes, attach as PDF
	if isinstance(label, (bytes, bytearray)):
		from erpnext_shipping.erpnext_shipping.shipping import save_label_as_attachment

		return save_label_as_attachment(shipment, bytes(label))

	# If it's a URL, return it
	return label


@frappe.whitelist()
def update_tracking(shipment, service_provider, shipment_id, delivery_notes=None):
	shipment_doc = frappe.get_doc("Shipment", shipment)
	if shipment_doc.service_provider != "Shiprocket":
		from erpnext_shipping.erpnext_shipping.shipping import update_tracking as base_update

		return base_update(shipment, service_provider, shipment_id, delivery_notes=delivery_notes)

	provider = _get_shiprocket_provider()
	if not provider:
		return None

	try:
		tracking = provider.update_tracking(shipment_doc=shipment_doc) or None
	except Exception:
		frappe.log_error(title="Shiprocket Tracking Update Failed")
		return None

	if not tracking:
		return None

	try:
		shipment_doc.db_set(
			{
				"awb_number": tracking.get("awb_number"),
				"tracking_status": tracking.get("tracking_status"),
				"tracking_status_info": tracking.get("tracking_status_info"),
				"tracking_url": tracking.get("tracking_url"),
				"extended_provider_data": _merge_extended_provider_data(
					shipment_doc, tracking.get("extended_provider_data")
				),
			}
		)
	except Exception:
		frappe.log_error(title="Shiprocket Tracking DB Update Failed")

	return tracking

def on_shipment_cancel(doc, method):
	"""Handle shipment cancellation - cancel on Shiprocket too"""
	if doc.service_provider != "Shiprocket":
		return

	if not doc.shiprocket_order_id:
		frappe.logger().info(f"Shipment {doc.name} cancelled locally (no Shiprocket order)")
		return

	current_statuses = {
		str(getattr(doc, "status", "") or "").strip().lower(),
		str(getattr(doc, "tracking_status", "") or "").strip().lower(),
	}
	if "delivered" in current_statuses:
		frappe.msgprint(
			_("Shipment is already delivered. Cannot cancel on Shiprocket."),
			alert=True,
			indicator="orange",
		)
		return
	
	try:
		provider = _get_shiprocket_provider()
		if provider and hasattr(provider, "cancel_shipment"):
			frappe.msgprint(_("Cancelling shipment on {0}...").format(doc.service_provider))
			result = provider.cancel_shipment(shipment_doc=doc)

			if result and result.get("extended_provider_data"):
				doc.db_set(
					"extended_provider_data",
					_merge_extended_provider_data(doc, result.get("extended_provider_data")),
				)
			
			if result and result.get("status") == "success":
				frappe.msgprint(
					_("✓ Shipment cancelled on {0}").format(doc.service_provider),
					alert=True,
					indicator="green"
				)
			else:
				frappe.msgprint(
					_("Unable to cancel on {0}. It may already be cancelled or in transit.").format(
						doc.service_provider
					),
					alert=True,
					indicator="orange"
				)
	except Exception as e:
		frappe.log_error(
			message=f"Shipment: {doc.name}\nProvider: {doc.service_provider}\nError: {str(e)}",
			title=f"{doc.service_provider} Cancel Failed"
		)
		frappe.msgprint(
			_("Shipment cancelled locally. Failed to notify {0}: {1}").format(doc.service_provider, str(e)),
			alert=True,
			indicator="orange"
		)
