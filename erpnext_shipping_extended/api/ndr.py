# -*- coding: utf-8 -*-
"""
NDR (Non-Delivery Report) Management for Shiprocket
Handles failed delivery attempts and customer actions
"""

import frappe
from frappe import _
import requests
from datetime import datetime


class ShiprocketNDRManager:
	"""Manages NDR (Non-Delivery Reports) for Shiprocket shipments"""
	
	def __init__(self, provider):
		self.provider = provider
		self.base_url = provider._get_base_url()
		self.auth_headers = provider._get_auth_headers()
	
	def get_ndr_list(self, **kwargs):
		"""
		Get list of shipments with failed delivery attempts
		API: GET /orders/processing/ndr
		"""
		try:
			response = requests.get(
				url=f"{self.base_url}/orders/processing/ndr",
				headers=self.auth_headers,
				params=kwargs,
				timeout=30
			)
			response.raise_for_status()
			result = response.json()
			
			ndr_list = result.get("data", [])
			
			return {
				"success": True,
				"ndr_count": len(ndr_list),
				"ndr_shipments": ndr_list
			}
			
		except Exception as e:
			frappe.log_error(message=str(e), title="Get NDR List Failed")
			return {"success": False, "message": str(e)}
	
	def take_ndr_action(self, *, awb, action, **kwargs):
		"""
		Take action on NDR shipment
		API: POST /orders/ndr/action
		
		Actions:
		- re-attempt: Schedule re-delivery
		- rto: Return to origin
		- cancel: Cancel shipment
		"""
		valid_actions = ["re-attempt", "rto", "cancel"]
		
		if action not in valid_actions:
			frappe.throw(_("Invalid NDR action. Must be one of: {0}").format(", ".join(valid_actions)))
		
		payload = {
			"awb": awb,
			"action": action
		}
		
		# Additional params for re-attempt
		if action == "re-attempt":
			payload.update({
				"customer_name": kwargs.get("customer_name", ""),
				"customer_phone": kwargs.get("customer_phone", ""),
				"address": kwargs.get("address", ""),
				"pincode": kwargs.get("pincode", ""),
				"remarks": kwargs.get("remarks", "Re-attempt delivery")
			})
		
		try:
			response = requests.post(
				url=f"{self.base_url}/orders/ndr/action",
				json=payload,
				headers=self.auth_headers,
				timeout=30
			)
			response.raise_for_status()
			result = response.json()
			
			if result.get("success") or str(result.get("status")).lower() == "success":
				action_text = {
					"re-attempt": "Re-delivery scheduled",
					"rto": "Marked for RTO",
					"cancel": "Shipment cancelled"
				}
				
				frappe.msgprint(
					_("✓ NDR Action: {0}").format(action_text.get(action, action)),
					alert=True,
					indicator="green"
				)
				
				return {
					"success": True,
					"action": action,
					"message": result.get("message", "Action completed")
				}
			else:
				return {
					"success": False,
					"message": result.get("message", "Action failed")
				}
				
		except requests.exceptions.HTTPError as e:
			error_detail = self._parse_error(e)
			frappe.log_error(
				message=f"AWB: {awb}\nAction: {action}\nError: {error_detail}",
				title="Shiprocket NDR Action Failed"
			)
			return {"success": False, "message": error_detail}
		except Exception as e:
			frappe.log_error(message=str(e), title="NDR Action Error")
			return {"success": False, "message": str(e)}
	
	def sync_ndr_to_erpnext(self):
		"""
		Sync NDR shipments to ERPNext
		Creates/updates comments on Shipment documents
		"""
		ndr_result = self.get_ndr_list()
		
		if not ndr_result.get("success"):
			return {"success": False, "message": "Failed to fetch NDR list"}
		
		ndr_shipments = ndr_result.get("ndr_shipments", [])
		synced_count = 0
		
		for ndr in ndr_shipments:
			awb = ndr.get("awb_number")
			ndr_status = ndr.get("ndr_status")
			ndr_reason = ndr.get("ndr_reason")
			
			# Find shipment in ERPNext
			shipments = frappe.get_all(
				"Shipment",
				filters={"awb_number": awb},
				fields=["name"]
			)
			
			if shipments:
				shipment_name = shipments[0].name
				
				# Add comment to shipment
				comment_text = f"""
					<strong>⚠️ Non-Delivery Report (NDR)</strong><br>
					Status: {ndr_status}<br>
					Reason: {ndr_reason}<br>
					Date: {ndr.get('ndr_date', 'N/A')}<br>
					<br>
					<em>Action required: Please take appropriate action from Shipment form.</em>
				"""
				
				frappe.get_doc({
					"doctype": "Comment",
					"comment_type": "Comment",
					"reference_doctype": "Shipment",
					"reference_name": shipment_name,
					"content": comment_text
				}).insert(ignore_permissions=True)
				
				# Update shipment status
				frappe.db.set_value("Shipment", shipment_name, "tracking_status", "NDR - Action Required")
				
				synced_count += 1
		
		frappe.db.commit()
		
		return {
			"success": True,
			"ndr_count": len(ndr_shipments),
			"synced_count": synced_count
		}
	
	def _parse_error(self, http_error):
		"""Parse HTTP error response"""
		try:
			error_resp = http_error.response.json()
			return error_resp.get("message", str(error_resp))
		except:
			return http_error.response.text


# Whitelisted API methods for ERPNext integration

@frappe.whitelist()
def get_ndr_shipments():
	"""Get list of shipments with failed delivery attempts"""
	from erpnext_shipping_extended.providers.shiprocket import ShiprocketProvider
	
	provider = ShiprocketProvider()
	ndr_mgr = ShiprocketNDRManager(provider)
	
	return ndr_mgr.get_ndr_list()


@frappe.whitelist()
def ndr_action(shipment_name, action, **kwargs):
	"""
	Take action on NDR shipment
	
	Actions:
	- re-attempt: Schedule re-delivery
	- rto: Return to origin
	- cancel: Cancel shipment
	"""
	from erpnext_shipping_extended.providers.shiprocket import ShiprocketProvider
	
	shipment = frappe.get_doc("Shipment", shipment_name)
	
	if not shipment.awb_number:
		frappe.throw(_("Shipment has no AWB number"))
	
	provider = ShiprocketProvider()
	ndr_mgr = ShiprocketNDRManager(provider)
	
	result = ndr_mgr.take_ndr_action(
		awb=shipment.awb_number,
		action=action,
		**kwargs
	)
	
	if result.get("success"):
		# Add comment to shipment
		frappe.get_doc({
			"doctype": "Comment",
			"comment_type": "Info",
			"reference_doctype": "Shipment",
			"reference_name": shipment.name,
			"content": f"NDR Action Taken: {action}"
		}).insert(ignore_permissions=True)
		
		frappe.db.commit()
	
	return result


@frappe.whitelist()
def sync_ndr_shipments():
	"""Sync all NDR shipments from Shiprocket to ERPNext"""
	from erpnext_shipping_extended.providers.shiprocket import ShiprocketProvider
	
	provider = ShiprocketProvider()
	ndr_mgr = ShiprocketNDRManager(provider)
	
	return ndr_mgr.sync_ndr_to_erpnext()


@frappe.whitelist()
def schedule_ndr_reattempt(shipment_name, customer_name=None, customer_phone=None, address=None, pincode=None, remarks=None):
	"""Schedule re-delivery for NDR shipment"""
	kwargs = {
		"customer_name": customer_name,
		"customer_phone": customer_phone,
		"address": address,
		"pincode": pincode,
		"remarks": remarks or "Customer requested re-delivery"
	}
	
	return ndr_action(shipment_name, "re-attempt", **kwargs)
