from __future__ import annotations

import frappe
from frappe.model.document import Document


class ShiprocketSettings(Document):
	def validate(self):
		if self.enabled:
			if not self.email:
				frappe.throw("Email is required")
			if not self.password:
				frappe.throw("Password is required")
