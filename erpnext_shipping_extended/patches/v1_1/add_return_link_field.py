from __future__ import annotations

import frappe


def execute():
	"""Backfill newer Shipment custom fields on already-installed sites."""
	try:
		from frappe.custom.doctype.custom_field.custom_field import create_custom_fields
	except Exception:
		frappe.log_error(title="ERPNext Shipping Extended: return link field patch import failed")
		return

	custom_fields = {
		"Shipment": [
			{
				"fieldname": "custom_return_against",
				"label": "Return Against",
				"fieldtype": "Link",
				"options": "Shipment",
				"read_only": 1,
				"insert_after": "extended_provider_data",
			}
		]
	}

	try:
		create_custom_fields(custom_fields, ignore_validate=True)
		frappe.db.commit()
	except Exception as e:
		frappe.log_error(
			message=f"Error: {str(e)}",
			title="ERPNext Shipping Extended: return link field patch failed",
		)
