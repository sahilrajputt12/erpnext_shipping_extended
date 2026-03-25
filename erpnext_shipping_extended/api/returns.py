# -*- coding: utf-8 -*-
"""
Return & RTO Management for Shiprocket
Handles return orders, reverse pickups, and RTO tracking
"""

import frappe
from frappe import _
import requests


class ShiprocketReturnManager:
	"""Manages returns and RTO for Shiprocket shipments"""
	
	def __init__(self, provider):
		self.provider = provider
		self.base_url = provider._get_base_url()
		self.auth_headers = provider._get_auth_headers()
	
	def create_return_order(self, *, shipment_doc, return_reason, **kwargs):
		"""
		Create return order in Shiprocket
		API: POST /orders/processing/return
		"""
		if not shipment_doc.shiprocket_order_id:
			frappe.throw(_("Shiprocket Order ID not found. Cannot create return."))
		
		payload = {
			"order_id": str(shipment_doc.shiprocket_order_id),
			"order_date": frappe.utils.today(),
			"channel_id": "4552960",  # Custom channel for returns
			"pickup_customer_name": shipment_doc.delivery_contact_name or "Customer",
			"pickup_last_name": "",
			"pickup_address": shipment_doc.delivery_address,
			"pickup_address_2": "",
			"pickup_city": shipment_doc.delivery_city,
			"pickup_state": shipment_doc.delivery_state,
			"pickup_country": shipment_doc.delivery_country,
			"pickup_pincode": shipment_doc.delivery_pincode,
			"pickup_email": shipment_doc.delivery_email,
			"pickup_phone": shipment_doc.delivery_contact_phone,
			"shipping_customer_name": shipment_doc.pickup_contact_name or "Warehouse",
			"shipping_last_name": "",
			"shipping_address": shipment_doc.pickup_address,
			"shipping_address_2": "",
			"shipping_city": shipment_doc.pickup_city,
			"shipping_country": shipment_doc.pickup_country,
			"shipping_pincode": shipment_doc.pickup_pincode,
			"shipping_state": shipment_doc.pickup_state,
			"shipping_email": shipment_doc.pickup_contact_email,
			"shipping_phone": shipment_doc.pickup_contact_phone,
			"order_items": self._get_return_items(shipment_doc),
			"payment_method": "Prepaid",
			"sub_total": shipment_doc.value_of_goods or 0,
			"length": shipment_doc.shipment_parcel[0].length if shipment_doc.shipment_parcel else 10,
			"breadth": shipment_doc.shipment_parcel[0].width if shipment_doc.shipment_parcel else 10,
			"height": shipment_doc.shipment_parcel[0].height if shipment_doc.shipment_parcel else 10,
			"weight": self._get_total_weight(shipment_doc),
			"return_reason": return_reason or "Customer Return"
		}
		
		try:
			response = requests.post(
				url=f"{self.base_url}/orders/create/return",
				json=payload,
				headers=self.auth_headers,
				timeout=30
			)
			response.raise_for_status()
			result = response.json()
			
			if result.get("order_id"):
				frappe.msgprint(
					_("✓ Return order created in Shiprocket. Order ID: {0}").format(result.get("order_id")),
					alert=True,
					indicator="green"
				)
				
				return {
					"success": True,
					"return_order_id": result.get("order_id"),
					"return_shipment_id": result.get("shipment_id"),
					"message": "Return order created successfully"
				}
			else:
				frappe.log_error(
					message=frappe.as_json(result, indent=2),
					title="Shiprocket Return Order Creation Response"
				)
				return {"success": False, "message": "Unexpected response from Shiprocket"}
				
		except requests.exceptions.HTTPError as e:
			error_detail = self._parse_error(e)
			frappe.log_error(
				message=f"Shipment: {shipment_doc.name}\nPayload: {frappe.as_json(payload, indent=2)}\nError: {error_detail}",
				title="Shiprocket Return Order Failed"
			)
			frappe.throw(_("Failed to create return order: {0}").format(error_detail))
		except Exception as e:
			frappe.log_error(
				message=f"Shipment: {shipment_doc.name}\nError: {str(e)}",
				title="Shiprocket Return Order Error"
			)
			frappe.throw(_("Error creating return order: {0}").format(str(e)))
	
	def schedule_return_pickup(self, *, return_order_id, pickup_date, **kwargs):
		"""
		Schedule pickup for return shipment
		API: POST /courier/assign/pickup
		"""
		payload = {
			"shipment_id": [int(return_order_id)],
			"pickup_date": pickup_date
		}
		
		try:
			response = requests.post(
				url=f"{self.base_url}/courier/assign/pickup",
				json=payload,
				headers=self.auth_headers,
				timeout=30
			)
			response.raise_for_status()
			result = response.json()
			
			if result.get("pickup_status") == 1:
				frappe.msgprint(
					_("✓ Return pickup scheduled for {0}").format(pickup_date),
					alert=True,
					indicator="green"
				)
				return {"success": True, "pickup_scheduled": True}
			else:
				return {"success": False, "message": result.get("message", "Pickup scheduling failed")}
				
		except requests.exceptions.HTTPError as e:
			error_detail = self._parse_error(e)
			frappe.log_error(
				message=f"Return Order: {return_order_id}\nError: {error_detail}",
				title="Shiprocket Return Pickup Failed"
			)
			return {"success": False, "message": error_detail}
		except Exception as e:
			frappe.log_error(message=str(e), title="Return Pickup Error")
			return {"success": False, "message": str(e)}
	
	def get_rto_orders(self, **kwargs):
		"""
		Get list of RTO (Return to Origin) orders
		API: GET /orders/processing/rto
		"""
		try:
			response = requests.get(
				url=f"{self.base_url}/orders/processing/rto",
				headers=self.auth_headers,
				timeout=30
			)
			response.raise_for_status()
			result = response.json()
			
			return {
				"success": True,
				"rto_orders": result.get("data", [])
			}
			
		except Exception as e:
			frappe.log_error(message=str(e), title="Get RTO Orders Failed")
			return {"success": False, "message": str(e)}
	
	def track_return_shipment(self, *, return_awb, **kwargs):
		"""
		Track return shipment
		API: GET /courier/track/awb/{awb}
		"""
		try:
			response = requests.get(
				url=f"{self.base_url}/courier/track/awb/{return_awb}",
				headers=self.auth_headers,
				timeout=30
			)
			response.raise_for_status()
			result = response.json()
			
			return {
				"success": True,
				"tracking_data": result
			}
			
		except Exception as e:
			frappe.log_error(message=str(e), title="Track Return Shipment Failed")
			return {"success": False, "message": str(e)}
	
	def _get_return_items(self, shipment_doc):
		"""Get return items from shipment"""
		items = []
		
		if shipment_doc.shipment_delivery_note:
			for dn_link in shipment_doc.shipment_delivery_note:
				dn = frappe.get_doc("Delivery Note", dn_link.delivery_note)
				for item in dn.items:
					items.append({
						"name": item.item_name or item.item_code,
						"sku": item.item_code,
						"units": int(item.qty),
						"selling_price": item.rate,
						"discount": 0,
						"tax": 0
					})
		
		# Fallback to basic item
		if not items:
			items.append({
				"name": "Return Item",
				"sku": "RETURN-ITEM",
				"units": 1,
				"selling_price": shipment_doc.value_of_goods or 100,
				"discount": 0,
				"tax": 0
			})
		
		return items
	
	def _get_total_weight(self, shipment_doc):
		"""Calculate total weight"""
		if shipment_doc.shipment_parcel:
			parcel = shipment_doc.shipment_parcel[0]
			if isinstance(parcel, dict):
				return float(parcel.get('weight') or 0.5)
			else:
				return float(getattr(parcel, 'weight', 0.5))
		return 0.5
	
	def _parse_error(self, http_error):
		"""Parse HTTP error response"""
		try:
			error_resp = http_error.response.json()
			return error_resp.get("message", str(error_resp))
		except:
			return http_error.response.text


# Whitelisted API methods for ERPNext integration

@frappe.whitelist()
def create_return_shipment(shipment_name, return_reason):
	"""Create return shipment in Shiprocket"""
	from erpnext_shipping_extended.providers.shiprocket import ShiprocketProvider
	
	shipment = frappe.get_doc("Shipment", shipment_name)
	
	if shipment.service_provider != "Shiprocket":
		frappe.throw(_("This shipment is not using Shiprocket"))
	
	if not shipment.shiprocket_order_id:
		frappe.throw(_("Original shipment has no Shiprocket Order ID"))
	
	provider = ShiprocketProvider()
	return_mgr = ShiprocketReturnManager(provider)
	
	result = return_mgr.create_return_order(
		shipment_doc=shipment,
		return_reason=return_reason
	)
	
	if result.get("success"):
		# Create a new Return Shipment document
		return_shipment = frappe.new_doc("Shipment")
		return_shipment.pickup_from_type = "Company"  # Pickup from customer
		return_shipment.delivery_to_type = "Company"  # Deliver to warehouse
		
		# Reverse the addresses
		return_shipment.pickup_address_name = shipment.delivery_address_name
		return_shipment.delivery_address_name = shipment.pickup_address_name
		
		return_shipment.pickup_date = frappe.utils.today()
		return_shipment.value_of_goods = shipment.value_of_goods
		return_shipment.description_of_content = f"Return for {shipment.name}"
		
		return_shipment.service_provider = "Shiprocket"
		return_shipment.shiprocket_order_id = str(result.get("return_order_id"))
		return_shipment.shiprocket_shipment_id = str(result.get("return_shipment_id"))
		
		# Link to original shipment
		return_shipment.shipment_type = "Return"
		return_shipment.custom_return_against = shipment.name
		
		return_shipment.insert()
		frappe.db.commit()
		
		frappe.msgprint(
			_("Return shipment created: {0}").format(return_shipment.name),
			alert=True,
			indicator="green"
		)
		
		return {
			"success": True,
			"return_shipment": return_shipment.name,
			"return_order_id": result.get("return_order_id")
		}
	
	return result


@frappe.whitelist()
def schedule_return_pickup(shipment_name, pickup_date):
	"""Schedule pickup for return shipment"""
	from erpnext_shipping_extended.providers.shiprocket import ShiprocketProvider
	
	shipment = frappe.get_doc("Shipment", shipment_name)
	
	if not shipment.shiprocket_shipment_id:
		frappe.throw(_("Return shipment has no Shiprocket Shipment ID"))
	
	provider = ShiprocketProvider()
	return_mgr = ShiprocketReturnManager(provider)
	
	return return_mgr.schedule_return_pickup(
		return_order_id=shipment.shiprocket_shipment_id,
		pickup_date=pickup_date
	)


@frappe.whitelist()
def get_rto_orders():
	"""Get list of RTO orders"""
	from erpnext_shipping_extended.providers.shiprocket import ShiprocketProvider
	
	provider = ShiprocketProvider()
	return_mgr = ShiprocketReturnManager(provider)
	
	return return_mgr.get_rto_orders()
