# -*- coding: utf-8 -*-
"""
Pickup Tracking & Management for Shiprocket
Handles pickup requests, tracking, and verification
"""

import frappe
from frappe import _
import requests


class ShiprocketPickupManager:
	"""Manages pickup requests and tracking for Shiprocket shipments"""
	
	def __init__(self, provider):
		self.provider = provider
		self.base_url = provider._get_base_url()
		self.auth_headers = provider._get_auth_headers()
	
	def generate_pickup(self, *, shipment_ids, pickup_date, **kwargs):
		"""
		Generate pickup request for shipments
		API: POST /courier/generate/pickup
		"""
		if not isinstance(shipment_ids, list):
			shipment_ids = [shipment_ids]
		
		payload = {
			"shipment_id": [int(sid) for sid in shipment_ids]
		}
		
		# Optional: specific pickup date
		if pickup_date:
			payload["pickup_date"] = pickup_date
		
		try:
			response = requests.post(
				url=f"{self.base_url}/courier/generate/pickup",
				json=payload,
				headers=self.auth_headers,
				timeout=30
			)
			response.raise_for_status()
			result = response.json()
			
			if result.get("pickup_status") == 1:
				pickup_token = result.get("response", {}).get("pickup_token_number")
				
				frappe.msgprint(
					_("✓ Pickup scheduled successfully. Pickup Token: {0}").format(pickup_token),
					alert=True,
					indicator="green"
				)
				
				return {
					"success": True,
					"pickup_token": pickup_token,
					"pickup_scheduled_date": result.get("response", {}).get("pickup_scheduled_date"),
					"message": "Pickup scheduled successfully"
				}
			else:
				error_msg = result.get("message", "Pickup scheduling failed")
				frappe.msgprint(error_msg, alert=True, indicator="red")
				return {"success": False, "message": error_msg}
				
		except requests.exceptions.HTTPError as e:
			error_detail = self._parse_error(e)
			frappe.log_error(
				message=f"Shipment IDs: {shipment_ids}\nError: {error_detail}",
				title="Shiprocket Pickup Generation Failed"
			)
			return {"success": False, "message": error_detail}
		except Exception as e:
			frappe.log_error(message=str(e), title="Pickup Generation Error")
			return {"success": False, "message": str(e)}
	
	def check_pickup_status(self, *, pickup_token, **kwargs):
		"""
		Check pickup status
		API: GET /courier/pickup/status/{pickup_token}
		"""
		try:
			response = requests.get(
				url=f"{self.base_url}/courier/pickup/status/{pickup_token}",
				headers=self.auth_headers,
				timeout=30
			)
			response.raise_for_status()
			result = response.json()
			
			return {
				"success": True,
				"pickup_status": result.get("pickup_status"),
				"pickup_data": result
			}
			
		except Exception as e:
			frappe.log_error(message=str(e), title="Check Pickup Status Failed")
			return {"success": False, "message": str(e)}
	
	def get_pending_pickups(self):
		"""
		Get list of shipments pending pickup
		Queries ERPNext for shipments with status 'Booked' but no pickup confirmation
		"""
		shipments = frappe.get_all(
			"Shipment",
			filters={
				"service_provider": "Shiprocket",
				"status": "Booked",
				"docstatus": 1
			},
			fields=["name", "awb_number", "shiprocket_shipment_id", "pickup_date", "creation"],
			order_by="creation desc",
			limit=50
		)
		
		pending = []
		
		for shipment in shipments:
			# Check if pickup token exists in extended_provider_data
			shipment_doc = frappe.get_doc("Shipment", shipment.name)
			
			has_pickup_token = False
			if shipment_doc.extended_provider_data:
				try:
					import json
					data = json.loads(shipment_doc.extended_provider_data)
					has_pickup_token = bool(data.get("shiprocket", {}).get("pickup_token"))
				except:
					pass
			
			if not has_pickup_token:
				pending.append({
					"shipment": shipment.name,
					"awb": shipment.awb_number,
					"shipment_id": shipment.shiprocket_shipment_id,
					"pickup_date": shipment.pickup_date,
					"age_days": (frappe.utils.now_datetime() - shipment.creation).days
				})
		
		return {
			"success": True,
			"pending_count": len(pending),
			"pending_shipments": pending
		}
	
	def bulk_generate_pickup(self, *, shipment_names, pickup_date=None):
		"""Generate pickup for multiple shipments"""
		shipment_ids = []
		
		for name in shipment_names:
			shipment = frappe.get_doc("Shipment", name)
			if shipment.shiprocket_shipment_id:
				shipment_ids.append(shipment.shiprocket_shipment_id)
		
		if not shipment_ids:
			return {"success": False, "message": "No valid shipments found"}
		
		result = self.generate_pickup(
			shipment_ids=shipment_ids,
			pickup_date=pickup_date
		)
		
		if result.get("success"):
			# Update shipments with pickup token
			pickup_token = result.get("pickup_token")
			
			for name in shipment_names:
				shipment = frappe.get_doc("Shipment", name)
				
				# Update extended_provider_data
				import json
				provider_data = {}
				if shipment.extended_provider_data:
					try:
						provider_data = json.loads(shipment.extended_provider_data)
					except:
						pass
				
				if "shiprocket" not in provider_data:
					provider_data["shiprocket"] = {}
				
				provider_data["shiprocket"]["pickup_token"] = pickup_token
				provider_data["shiprocket"]["pickup_scheduled_date"] = result.get("pickup_scheduled_date")
				
				frappe.db.set_value(
					"Shipment",
					name,
					"extended_provider_data",
					json.dumps(provider_data)
				)
			
			frappe.db.commit()
		
		return result
	
	def _parse_error(self, http_error):
		"""Parse HTTP error response"""
		try:
			error_resp = http_error.response.json()
			return error_resp.get("message", str(error_resp))
		except:
			return http_error.response.text


# Whitelisted API methods for ERPNext integration

@frappe.whitelist()
def generate_pickup_request(shipment_name, pickup_date=None):
	"""Generate pickup request for a shipment"""
	from erpnext_shipping_extended.providers.shiprocket import ShiprocketProvider
	
	shipment = frappe.get_doc("Shipment", shipment_name)
	
	if not shipment.shiprocket_shipment_id:
		frappe.throw(_("Shipment has no Shiprocket Shipment ID"))
	
	provider = ShiprocketProvider()
	pickup_mgr = ShiprocketPickupManager(provider)
	
	result = pickup_mgr.generate_pickup(
		shipment_ids=[shipment.shiprocket_shipment_id],
		pickup_date=pickup_date or shipment.pickup_date
	)
	
	if result.get("success"):
		# Update shipment with pickup token
		import json
		provider_data = {}
		if shipment.extended_provider_data:
			try:
				provider_data = json.loads(shipment.extended_provider_data)
			except:
				pass
		
		if "shiprocket" not in provider_data:
			provider_data["shiprocket"] = {}
		
		provider_data["shiprocket"]["pickup_token"] = result.get("pickup_token")
		provider_data["shiprocket"]["pickup_scheduled_date"] = result.get("pickup_scheduled_date")
		
		shipment.extended_provider_data = json.dumps(provider_data)
		shipment.save(ignore_permissions=True)
		frappe.db.commit()
	
	return result


@frappe.whitelist()
def check_pickup_status_by_shipment(shipment_name):
	"""Check pickup status for a shipment"""
	from erpnext_shipping_extended.providers.shiprocket import ShiprocketProvider
	
	shipment = frappe.get_doc("Shipment", shipment_name)
	
	# Get pickup token from extended_provider_data
	pickup_token = None
	if shipment.extended_provider_data:
		try:
			import json
			data = json.loads(shipment.extended_provider_data)
			pickup_token = data.get("shiprocket", {}).get("pickup_token")
		except:
			pass
	
	if not pickup_token:
		return {"success": False, "message": "No pickup token found. Please generate pickup first."}
	
	provider = ShiprocketProvider()
	pickup_mgr = ShiprocketPickupManager(provider)
	
	return pickup_mgr.check_pickup_status(pickup_token=pickup_token)


@frappe.whitelist()
def get_pending_pickups():
	"""Get list of shipments pending pickup"""
	from erpnext_shipping_extended.providers.shiprocket import ShiprocketProvider
	
	provider = ShiprocketProvider()
	pickup_mgr = ShiprocketPickupManager(provider)
	
	return pickup_mgr.get_pending_pickups()


@frappe.whitelist()
def bulk_generate_pickups(shipment_names, pickup_date=None):
	"""Generate pickup for multiple shipments"""
	from erpnext_shipping_extended.providers.shiprocket import ShiprocketProvider
	
	import json
	if isinstance(shipment_names, str):
		shipment_names = json.loads(shipment_names)
	
	provider = ShiprocketProvider()
	pickup_mgr = ShiprocketPickupManager(provider)
	
	return pickup_mgr.bulk_generate_pickup(
		shipment_names=shipment_names,
		pickup_date=pickup_date
	)
