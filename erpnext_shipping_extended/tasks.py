from __future__ import annotations

import frappe


def update_tracking_daily():
	"""Daily scheduler: update tracking for Booked Shipments not Delivered."""
	try:
		from erpnext_shipping.erpnext_shipping.utils import update_tracking_info_daily

		# This will call erpnext_shipping.shipping.update_tracking, which we override to include Shiprocket.
		return update_tracking_info_daily()
	except Exception:
		frappe.log_error(title="ERPNext Shipping Extended: Daily Tracking Update Failed")

def sync_pending_awbs():
	"""Hourly task to sync pending AWBs"""
	from erpnext_shipping_extended.api.awb_sync import sync_pending_awbs as sync_awbs
	sync_awbs()
