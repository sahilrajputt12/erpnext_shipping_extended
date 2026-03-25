# -*- coding: utf-8 -*-
"""
Manifest Generation & POD (Proof of Delivery) Management
Handles bulk manifest creation and POD downloads
"""

import frappe
from frappe import _
import requests
import base64


class ShiprocketManifestManager:
	"""Manages manifest generation and POD downloads for Shiprocket shipments"""
	
	def __init__(self, provider):
		self.provider = provider
		self.base_url = provider._get_base_url()
		self.auth_headers = provider._get_auth_headers()
	
	def generate_manifest(self, *, shipment_ids, **kwargs):
		"""
		Generate manifest for shipments
		API: POST /courier/generate/manifest
		"""
		if not isinstance(shipment_ids, list):
			shipment_ids = [shipment_ids]
		
		payload = {
			"shipment_id": [int(sid) for sid in shipment_ids]
		}
		
		try:
			response = requests.post(
				url=f"{self.base_url}/courier/generate/manifest",
				json=payload,
				headers=self.auth_headers,
				timeout=30
			)
			response.raise_for_status()
			result = response.json()
			
			if result.get("status") == "success" or result.get("manifest_url"):
				manifest_url = result.get("manifest_url") or result.get("response", {}).get("manifest_url")
				
				frappe.msgprint(
					_("✓ Manifest generated successfully"),
					alert=True,
					indicator="green"
				)
				
				return {
					"success": True,
					"manifest_url": manifest_url,
					"shipment_count": len(shipment_ids)
				}
			else:
				error_msg = result.get("message", "Manifest generation failed")
				return {"success": False, "message": error_msg}
				
		except requests.exceptions.HTTPError as e:
			error_detail = self._parse_error(e)
			frappe.log_error(
				message=f"Shipment IDs: {shipment_ids}\nError: {error_detail}",
				title="Shiprocket Manifest Generation Failed"
			)
			return {"success": False, "message": error_detail}
		except Exception as e:
			frappe.log_error(message=str(e), title="Manifest Generation Error")
			return {"success": False, "message": str(e)}
	
	def print_manifest(self, *, manifest_url, **kwargs):
		"""
		Download manifest PDF
		"""
		try:
			response = requests.get(
				url=manifest_url,
				headers=self.auth_headers,
				timeout=60
			)
			response.raise_for_status()
			
			return {
				"success": True,
				"pdf_content": response.content,
				"content_type": response.headers.get("Content-Type", "application/pdf")
			}
			
		except Exception as e:
			frappe.log_error(message=str(e), title="Manifest Download Failed")
			return {"success": False, "message": str(e)}
	
	def get_proof_of_delivery(self, *, awb, **kwargs):
		"""
		Download Proof of Delivery (POD)
		API: GET /courier/pod/{awb}
		"""
		try:
			response = requests.get(
				url=f"{self.base_url}/courier/pod",
				params={"awb": awb},
				headers=self.auth_headers,
				timeout=30
			)
			response.raise_for_status()
			result = response.json()
			
			if result.get("pod_url"):
				pod_url = result.get("pod_url")
				
				# Download the POD file
				pod_response = requests.get(pod_url, timeout=60)
				pod_response.raise_for_status()
				
				return {
					"success": True,
					"pod_url": pod_url,
					"pod_content": pod_response.content,
					"content_type": pod_response.headers.get("Content-Type", "application/pdf")
				}
			else:
				return {
					"success": False,
					"message": result.get("message", "POD not available yet")
				}
				
		except Exception as e:
			frappe.log_error(message=f"AWB: {awb}\nError: {str(e)}", title="POD Download Failed")
			return {"success": False, "message": str(e)}
	
	def get_shipping_invoice(self, *, awb, **kwargs):
		"""
		Download shipping invoice from courier
		API: GET /courier/invoice/{awb}
		"""
		try:
			response = requests.get(
				url=f"{self.base_url}/courier/invoice",
				params={"awb": awb},
				headers=self.auth_headers,
				timeout=30
			)
			response.raise_for_status()
			result = response.json()
			
			if result.get("invoice_url"):
				invoice_url = result.get("invoice_url")
				
				# Download the invoice
				inv_response = requests.get(invoice_url, timeout=60)
				inv_response.raise_for_status()
				
				return {
					"success": True,
					"invoice_url": invoice_url,
					"invoice_content": inv_response.content,
					"content_type": inv_response.headers.get("Content-Type", "application/pdf")
				}
			else:
				return {
					"success": False,
					"message": result.get("message", "Invoice not available yet")
				}
				
		except Exception as e:
			frappe.log_error(message=f"AWB: {awb}\nError: {str(e)}", title="Invoice Download Failed")
			return {"success": False, "message": str(e)}
	
	def _parse_error(self, http_error):
		"""Parse HTTP error response"""
		try:
			error_resp = http_error.response.json()
			return error_resp.get("message", str(error_resp))
		except:
			return http_error.response.text


# Whitelisted API methods for ERPNext integration

@frappe.whitelist()
def generate_manifest_for_shipments(shipment_names):
	"""Generate manifest for selected shipments"""
	from erpnext_shipping_extended.providers.shiprocket import ShiprocketProvider
	
	import json
	if isinstance(shipment_names, str):
		shipment_names = json.loads(shipment_names)
	
	# Get Shiprocket shipment IDs
	shipment_ids = []
	for name in shipment_names:
		shipment = frappe.get_doc("Shipment", name)
		if shipment.shiprocket_shipment_id:
			shipment_ids.append(shipment.shiprocket_shipment_id)
	
	if not shipment_ids:
		return {"success": False, "message": "No valid Shiprocket shipments found"}
	
	provider = ShiprocketProvider()
	manifest_mgr = ShiprocketManifestManager(provider)
	
	result = manifest_mgr.generate_manifest(shipment_ids=shipment_ids)
	
	if result.get("success"):
		# Download and attach manifest
		manifest_result = manifest_mgr.print_manifest(manifest_url=result.get("manifest_url"))
		
		if manifest_result.get("success"):
			# Save as file
			file_doc = frappe.get_doc({
				"doctype": "File",
				"file_name": f"Manifest_{frappe.utils.now_datetime().strftime('%Y%m%d_%H%M%S')}.pdf",
				"is_private": 0,
				"content": manifest_result.get("pdf_content")
			})
			file_doc.insert(ignore_permissions=True)
			frappe.db.commit()
			
			result["file_url"] = file_doc.file_url
	
	return result


@frappe.whitelist()
def download_pod(shipment_name):
	"""Download Proof of Delivery for a shipment"""
	from erpnext_shipping_extended.providers.shiprocket import ShiprocketProvider
	
	shipment = frappe.get_doc("Shipment", shipment_name)
	
	if not shipment.awb_number:
		frappe.throw(_("Shipment has no AWB number"))
	
	if shipment.status != "Delivered":
		frappe.msgprint(
			_("⚠️ POD may not be available yet. Shipment status: {0}").format(shipment.status),
			alert=True,
			indicator="orange"
		)
	
	provider = ShiprocketProvider()
	manifest_mgr = ShiprocketManifestManager(provider)
	
	result = manifest_mgr.get_proof_of_delivery(awb=shipment.awb_number)
	
	if result.get("success"):
		# Save POD as attachment to Shipment
		file_doc = frappe.get_doc({
			"doctype": "File",
			"file_name": f"POD_{shipment.awb_number}.pdf",
			"attached_to_doctype": "Shipment",
			"attached_to_name": shipment.name,
			"is_private": 1,
			"content": result.get("pod_content")
		})
		file_doc.insert(ignore_permissions=True)
		frappe.db.commit()
		
		frappe.msgprint(
			_("✓ POD downloaded and attached to shipment"),
			alert=True,
			indicator="green"
		)
		
		result["file_url"] = file_doc.file_url
	
	return result


@frappe.whitelist()
def download_shipping_invoice(shipment_name):
	"""Download shipping invoice for a shipment"""
	from erpnext_shipping_extended.providers.shiprocket import ShiprocketProvider
	
	shipment = frappe.get_doc("Shipment", shipment_name)
	
	if not shipment.awb_number:
		frappe.throw(_("Shipment has no AWB number"))
	
	provider = ShiprocketProvider()
	manifest_mgr = ShiprocketManifestManager(provider)
	
	result = manifest_mgr.get_shipping_invoice(awb=shipment.awb_number)
	
	if result.get("success"):
		# Save invoice as attachment to Shipment
		file_doc = frappe.get_doc({
			"doctype": "File",
			"file_name": f"Shipping_Invoice_{shipment.awb_number}.pdf",
			"attached_to_doctype": "Shipment",
			"attached_to_name": shipment.name,
			"is_private": 1,
			"content": result.get("invoice_content")
		})
		file_doc.insert(ignore_permissions=True)
		frappe.db.commit()
		
		frappe.msgprint(
			_("✓ Shipping invoice downloaded and attached"),
			alert=True,
			indicator="green"
		)
		
		result["file_url"] = file_doc.file_url
	
	return result


@frappe.whitelist()
def bulk_download_pods(shipment_names):
	"""Download PODs for multiple shipments"""
	import json
	if isinstance(shipment_names, str):
		shipment_names = json.loads(shipment_names)
	
	results = []
	
	for name in shipment_names:
		try:
			result = download_pod(name)
			results.append({
				"shipment": name,
				"success": result.get("success"),
				"message": result.get("message", "Downloaded")
			})
		except Exception as e:
			results.append({
				"shipment": name,
				"success": False,
				"message": str(e)
			})
	
	success_count = len([r for r in results if r["success"]])
	
	return {
		"success": True,
		"total": len(shipment_names),
		"success_count": success_count,
		"failed_count": len(shipment_names) - success_count,
		"results": results
	}
