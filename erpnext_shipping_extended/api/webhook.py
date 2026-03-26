"""
Shiprocket Webhook Handler
Handles real-time shipment status updates from Shiprocket

Webhook Events:
- order_pickup: Order picked up by courier
- in_transit: Shipment in transit
- out_for_delivery: Out for delivery
- delivered: Successfully delivered
- rto_initiated: Return to Origin initiated
- rto_delivered: Returned to seller
- ndr: Non-Delivery Report (failed delivery attempt)
- lost: Shipment lost
- damaged: Shipment damaged

Setup Instructions:
1. Go to Shiprocket Dashboard > Settings > Webhooks
2. Add Webhook URL: https://your-site.com/api/method/erpnext_shipping_extended.api.webhook.shiprocket_webhook
3. Enable events you want to track
4. Copy Webhook Secret (if provided by Shiprocket)
5. Add secret to Shiprocket Settings doctype (needs custom field)
"""

from __future__ import annotations

import hashlib
import hmac
import json
from datetime import datetime

import frappe
from frappe import _

TRACKING_STATUS_INFO_MAX_LENGTH = 140


def _build_webhook_tracking_status_info(event_type, data):
	"""Store a compact summary in Shipment.tracking_status_info."""
	parts = [
		event_type,
		data.get("current_status") or data.get("status_label") or data.get("status"),
		data.get("location") or data.get("city"),
		data.get("event_time") or data.get("scan_date") or data.get("updated_at"),
	]
	summary = " | ".join(str(part).strip() for part in parts if part)
	if summary:
		return summary[:TRACKING_STATUS_INFO_MAX_LENGTH]
	return str(event_type or "Shiprocket Update")[:TRACKING_STATUS_INFO_MAX_LENGTH]


@frappe.whitelist(allow_guest=True)
def shiprocket_webhook():
	"""
	Main webhook endpoint for Shiprocket events
	Authenticated via signature verification or IP whitelist
	"""
	try:
		# Health-check endpoint (Option A): allow GET to verify route is active
		if getattr(frappe.local, "request", None) and frappe.local.request.method == "GET":
			return {"status": "ok", "message": "Shiprocket webhook endpoint is active"}

		# Get raw request data
		data = frappe.local.form_dict
		
		# Log incoming webhook (for debugging)
		if frappe.conf.get("log_shiprocket_webhooks"):
			frappe.log_error(
				message=frappe.as_json(data, indent=2),
				title="Shiprocket Webhook Received"
			)
		
		# Verify webhook authenticity
		# Temporary bypass for testing - remove in production
		if frappe.conf.get("developer_mode") or frappe.local.request_ip in ["127.0.0.1", "::1"]:
			frappe.logger().info("Webhook bypassed for local testing")
		elif not _verify_webhook_signature():
			frappe.log_error(
				message="Signature verification failed",
				title="Shiprocket Webhook: Unauthorized"
			)
			return {"status": "error", "message": "Unauthorized"}
		
		# Extract event type and data
		event_type = data.get("event") or data.get("status")
		awb = data.get("awb") or data.get("awb_code")
		order_id = data.get("order_id") or data.get("id")
		
		if not awb and not order_id:
			frappe.log_error(
				message=frappe.as_json(data, indent=2),
				title="Shiprocket Webhook: Missing Identifier"
			)
			return {"status": "error", "message": "Missing AWB or Order ID"}
		
		# Find shipment in ERPNext
		shipment = _find_shipment(awb=awb, order_id=order_id)
		
		if not shipment:
			# Not an error - might be a shipment not created via API
			frappe.logger().info(f"Webhook received for unknown shipment: AWB={awb}, Order ID={order_id}")
			return {"status": "ok", "message": "Shipment not found in ERPNext"}
		
		# Process webhook event
		result = _process_webhook_event(shipment, event_type, data)
		
		return {"status": "ok", "shipment": shipment.name, "processed": result}
		
	except Exception as e:
		frappe.log_error(
			message=f"Error: {str(e)}\n\nData: {frappe.as_json(frappe.local.form_dict, indent=2)}",
			title="Shiprocket Webhook Error"
		)
		return {"status": "error", "message": str(e)}


def _verify_webhook_signature():
	"""
	Verify webhook signature (if Shiprocket provides one)
	Falls back to IP whitelist only when explicitly allowed
	"""
	settings = frappe.get_single("Shiprocket Settings")
	webhook_secret = settings.get_password("webhook_secret") if getattr(settings, "webhook_secret", None) else None
	signature_required = bool(getattr(settings, "enable_webhook_signature", 1))
	allow_insecure_fallback = bool(getattr(settings, "allow_insecure_webhook_fallback", 0))

	if signature_required and not webhook_secret:
		frappe.logger().warning("Shiprocket webhook rejected because webhook signature verification is enabled but no secret is configured")
		return False

	if not signature_required:
		return _verify_ip_whitelist() if allow_insecure_fallback else False

	if not webhook_secret:
		return _verify_ip_whitelist() if allow_insecure_fallback else False
	
	signature = frappe.get_request_header("X-Shiprocket-Signature") or \
	            frappe.get_request_header("X-Webhook-Signature")
	
	if not signature:
		frappe.logger().warning("Webhook signature missing in request")
		return _verify_ip_whitelist() if allow_insecure_fallback else False
	
	# Get raw request body
	raw_body = frappe.request.get_data(as_text=True)
	
	# Calculate expected signature
	expected_signature = hmac.new(
		webhook_secret.encode(),
		raw_body.encode(),
		hashlib.sha256
	).hexdigest()
	
	# Compare signatures
	if hmac.compare_digest(signature, expected_signature):
		return True
	
	frappe.logger().warning(f"Webhook signature mismatch. Expected: {expected_signature}, Got: {signature}")
	return False


def _verify_ip_whitelist():
	"""
	Verify request is from Shiprocket's IP range
	Only intended as an explicitly enabled temporary fallback.
	"""
	client_ip = frappe.local.request_ip
	
	# Placeholder ranges for controlled environments only.
	allowed_ips = [
		"127.0.0.1",  # Localhost for testing
		"::1",  # IPv6 localhost
	]
	
	# In development mode, allow all
	if frappe.conf.get("developer_mode"):
		return True
	
	# Check if IP is in whitelist
	# For production, implement proper IP range checking
	# This is a simple string match for now
	for allowed_ip in allowed_ips:
		if client_ip.startswith(allowed_ip.split("/")[0].rsplit(".", 1)[0]):
			return True
	
	frappe.logger().warning(f"Webhook request from unauthorized IP: {client_ip}")
	return False


def _find_shipment(awb=None, order_id=None):
	"""Find shipment by AWB or Shiprocket Order ID"""
	filters = {"service_provider": "Shiprocket", "docstatus": 1}
	
	if awb:
		filters["awb_number"] = awb
	elif order_id:
		filters["shiprocket_order_id"] = str(order_id)
	else:
		return None
	
	shipments = frappe.get_all("Shipment", filters=filters, limit=1)
	
	if not shipments:
		return None
	
	return frappe.get_doc("Shipment", shipments[0].name)


def _process_webhook_event(shipment, event_type, data):
	"""
	Process webhook event and update shipment
	Returns True if processed, False if ignored
	"""
	# Prevent duplicate processing using idempotency
	webhook_id = data.get("webhook_id") or data.get("id")
	if webhook_id and _is_webhook_processed(shipment.name, webhook_id):
		frappe.logger().info(f"Webhook {webhook_id} already processed for {shipment.name}")
		return False
	
	# Map Shiprocket events to ERPNext statuses
	event_status_map = {
		"order_pickup": "In Transit",
		"in_transit": "In Transit",
		"out_for_delivery": "In Transit",
		"delivered": "Delivered",
		"rto_initiated": "In Transit",
		"rto_delivered": "Delivered",
		"ndr": "In Transit",
		"lost": "Lost",
		"damaged": "Lost",
		"canceled": "Cancelled",
		"rto": "In Transit",
	}
	
	# Get new status
	new_status = event_status_map.get(str(event_type).lower())
	
	if not new_status:
		frappe.logger().info(f"Unhandled webhook event type: {event_type}")
		return False
	
	# Don't downgrade status (e.g., don't move from Delivered back to In Transit)
	status_priority = {
		"Booked": 1,
		"In Transit": 2,
		"Delivered": 3,
		"Lost": 3,
		"Cancelled": 3,
	}
	
	current_priority = status_priority.get(shipment.status, 0)
	new_priority = status_priority.get(new_status, 0)
	
	if new_priority < current_priority:
		frappe.logger().info(f"Ignoring status downgrade: {shipment.status} -> {new_status}")
		return False
	
	# Update shipment
	update_data = {
		"status": new_status,
		"tracking_status": str(event_type),
		"tracking_status_info": _build_webhook_tracking_status_info(event_type, data),
	}
	
	# Update AWB if provided and missing
	if data.get("awb") and not shipment.awb_number:
		update_data["awb_number"] = data.get("awb")
	
	# Update tracking URL if provided
	if data.get("tracking_url"):
		update_data["tracking_url"] = data.get("tracking_url")
	
	# Store extended data
	try:
		extended_data = json.loads(shipment.extended_provider_data or "{}")
		if "shiprocket" not in extended_data:
			extended_data["shiprocket"] = {}
		extended_data["shiprocket"]["last_webhook"] = {
			"event": event_type,
			"timestamp": datetime.now().isoformat(),
			"data": data
		}
		update_data["extended_provider_data"] = frappe.as_json(extended_data)
	except:
		pass
	
	# Update shipment
	shipment.db_set(update_data)
	frappe.db.commit()
	
	# Mark webhook as processed
	if webhook_id:
		_mark_webhook_processed(shipment.name, webhook_id)
	
	# Send notification if delivered
	if new_status == "Delivered" and frappe.conf.get("send_delivery_notifications"):
		_send_delivery_notification(shipment)
	
	frappe.logger().info(f"✓ Webhook processed: {shipment.name} -> {new_status} ({event_type})")
	
	return True


def _is_webhook_processed(shipment_name, webhook_id):
	"""Check if webhook has already been processed (idempotency)"""
	cache_key = f"webhook_processed:{shipment_name}:{webhook_id}"
	return frappe.cache().get(cache_key)


def _mark_webhook_processed(shipment_name, webhook_id):
	"""Mark webhook as processed (store in cache for 24 hours)"""
	cache_key = f"webhook_processed:{shipment_name}:{webhook_id}"
	frappe.cache().set(cache_key, True, expires_in_sec=86400)  # 24 hours


def _send_delivery_notification(shipment):
	"""Send email notification when shipment is delivered"""
	try:
		# Get customer email
		if shipment.delivery_to_type == "Customer":
			customer = frappe.get_doc("Customer", shipment.delivery_customer)
			if customer.email_id:
				frappe.sendmail(
					recipients=[customer.email_id],
					subject=f"Your order {shipment.name} has been delivered",
					message=f"""
					<p>Dear {customer.customer_name},</p>
					<p>Your shipment <strong>{shipment.name}</strong> has been successfully delivered.</p>
					<p><strong>AWB Number:</strong> {shipment.awb_number}</p>
					<p>Thank you for your business!</p>
					""",
					delayed=True
				)
	except Exception as e:
		frappe.log_error(
			message=f"Shipment: {shipment.name}\nError: {str(e)}",
			title="Delivery Notification Failed"
		)


@frappe.whitelist()
def sync_awb_manually(shipment_name):
	"""
	Manual AWB sync from Shiprocket
	Used by "Sync AWB" button in UI
	"""
	from erpnext_shipping_extended.providers.shiprocket import ShiprocketProvider
	
	shipment = frappe.get_doc("Shipment", shipment_name)
	
	if shipment.service_provider != "Shiprocket":
		return {"success": False, "message": "Not a Shiprocket shipment"}
	
	if shipment.awb_number:
		return {"success": True, "awb": shipment.awb_number, "message": "AWB already exists"}
	
	if not shipment.shiprocket_order_id:
		return {"success": False, "message": "Shiprocket Order ID not found"}
	
	try:
		provider = ShiprocketProvider()
		awb = provider.sync_awb_from_shiprocket(shipment)
		
		if awb:
			return {"success": True, "awb": awb, "message": f"AWB synced: {awb}"}
		else:
			return {
				"success": False,
				"message": "AWB not assigned yet. Please try again in a few minutes."
			}
	except Exception as e:
		frappe.log_error(
			message=f"Shipment: {shipment_name}\nError: {str(e)}",
			title="Manual AWB Sync Failed"
		)
		return {"success": False, "message": str(e)}
