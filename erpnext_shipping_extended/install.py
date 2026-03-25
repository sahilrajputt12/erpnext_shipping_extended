from __future__ import annotations

import frappe


def after_install():
	"""Create module + custom fields after app install."""
	try:
		from erpnext_shipping_extended.patches.v1_0.add_custom_fields import execute

		execute()
	except Exception:
		frappe.log_error(title="ERPNext Shipping Extended: after_install failed")
