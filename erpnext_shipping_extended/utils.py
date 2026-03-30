from __future__ import annotations

import frappe
from frappe import _


def _get_pickup_address_name(doc) -> str | None:
	"""Resolve pickup address across custom and core Shipment field names."""
	return doc.get("pickup_from_address") or doc.get("pickup_address_name")


def validate_pickup_address_fields(address_name: str):
	"""Validate pickup address has the minimum fields required by Shiprocket."""
	if not address_name:
		return False, _("No address specified")

	try:
		address = frappe.get_doc("Address", address_name)
	except Exception as exc:
		return False, str(exc)

	required_fields = {
		"address_line1": _("Address Line 1"),
		"city": _("City"),
		"state": _("State"),
		"pincode": _("Pincode"),
		"country": _("Country"),
	}
	missing = [label for fieldname, label in required_fields.items() if not address.get(fieldname)]
	if missing:
		return False, _("Missing fields: {0}").format(", ".join(missing))

	return True, _("Valid")


def validate_shiprocket_shipment(doc, method=None):
	"""
	Validate Shiprocket shipments have a usable pickup address.
	Supports both the custom `pickup_from_address` field from the guide
	and ERPNext's standard `pickup_address_name` field.
	"""
	service_provider = (doc.get("service_provider") or "").lower()
	if "shiprocket" not in service_provider:
		return

	address_name = _get_pickup_address_name(doc)
	if not address_name:
		frappe.throw(
			_("Pickup From Address is mandatory for Shiprocket shipments. Please select a pickup location."),
			title=_("Missing Pickup Address"),
		)

	is_valid, message = validate_pickup_address_fields(address_name)
	if not is_valid:
		frappe.throw(
			_("Pickup Address '{0}' is incomplete: {1}").format(address_name, message),
			title=_("Incomplete Pickup Address"),
		)
