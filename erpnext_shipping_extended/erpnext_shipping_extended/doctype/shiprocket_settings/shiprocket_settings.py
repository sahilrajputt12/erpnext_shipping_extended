from __future__ import annotations

import frappe
from frappe import _
from frappe.model.document import Document
from frappe.utils import get_url

from erpnext_shipping_extended.providers.shiprocket import (
	ShiprocketProvider,
	get_cached_shiprocket_auth_status,
)


def build_shiprocket_webhook_url() -> str:
	return f"{get_url()}/api/method/erpnext_shipping_extended.api.webhook.shiprocket_webhook"


class ShiprocketSettings(Document):
	def validate(self):
		if self.enabled:
			if not self.email:
				frappe.throw(_("Email is required"))
			if not self.password:
				frappe.throw(_("Password is required"))
			if self.enable_webhook_signature and not self.get_password("webhook_secret"):
				frappe.throw(_("Webhook Secret is required when webhook signature verification is enabled"))

		self.webhook_url = build_shiprocket_webhook_url()

	def get_webhook_url(self) -> str:
		return build_shiprocket_webhook_url()


@frappe.whitelist()
def get_shiprocket_webhook_url() -> str:
	return build_shiprocket_webhook_url()


@frappe.whitelist()
def get_shiprocket_auth_status() -> dict[str, str | None]:
	settings = frappe.get_single("Shiprocket Settings")
	if settings.enabled and settings.email and settings.password:
		try:
			ShiprocketProvider().authenticate()
		except Exception:
			pass

	return get_cached_shiprocket_auth_status()
