"""
AWB Sync Scheduler Task
Automatically syncs missing AWB numbers for booked Shiprocket shipments
Run: Daily or Hourly
"""

from __future__ import annotations

import frappe
from frappe import _


def sync_pending_awbs():
	"""
	Scheduler task to sync AWB for shipments that don't have it yet
	This handles cases where AWB generation was delayed during shipment creation
	"""
	frappe.logger().info("Starting AWB sync for pending Shiprocket shipments...")
	
	# Get all Shiprocket shipments without AWB
	pending_shipments = frappe.get_all(
		"Shipment",
		filters={
			"service_provider": "Shiprocket",
			"shiprocket_order_id": ["!=", ""],
			"awb_number": ["in", ["", None]],
			"status": ["in", ["Booked", "In Transit"]],
			"docstatus": 1,
		},
		fields=["name", "shiprocket_order_id", "creation"],
		order_by="creation desc",
		limit=100  # Process max 100 per run to avoid timeouts
	)
	
	if not pending_shipments:
		frappe.logger().info("No pending AWB shipments found")
		return
	
	frappe.logger().info(f"Found {len(pending_shipments)} shipments pending AWB sync")
	
	from erpnext_shipping_extended.providers.shiprocket import ShiprocketProvider
	
	provider = ShiprocketProvider()
	
	success_count = 0
	failed_count = 0
	
	for shipment_data in pending_shipments:
		try:
			shipment = frappe.get_doc("Shipment", shipment_data.name)
			
			# Try to sync AWB
			awb = provider.sync_awb_from_shiprocket(shipment)
			
			if awb:
				success_count += 1
				frappe.logger().info(f"✓ AWB synced for {shipment.name}: {awb}")
			else:
				failed_count += 1
				frappe.logger().warning(f"✗ AWB not yet assigned for {shipment.name}")
				
		except Exception as e:
			failed_count += 1
			frappe.log_error(
				message=f"Shipment: {shipment_data.name}\nError: {str(e)}",
				title="AWB Sync Failed"
			)
			frappe.logger().error(f"✗ Error syncing AWB for {shipment_data.name}: {str(e)}")
	
	# Log summary
	summary = f"AWB Sync Complete: {success_count} synced, {failed_count} pending/failed"
	frappe.logger().info(summary)
	
	# Send notification if there are failures (optional)
	if failed_count > 0 and frappe.conf.get("send_awb_sync_alerts"):
		send_awb_sync_alert(success_count, failed_count, pending_shipments[:10])


def send_awb_sync_alert(success_count, failed_count, sample_shipments):
	"""Send email alert to System Manager about pending AWBs"""
	try:
		recipients = frappe.get_all(
			"Has Role",
			filters={"role": "System Manager", "parenttype": "User"},
			fields=["parent"],
			distinct=True
		)
		
		if not recipients:
			return
		
		recipient_emails = [r.parent for r in recipients if frappe.db.get_value("User", r.parent, "enabled")]
		
		if not recipient_emails:
			return
		
		shipment_list = "<ul>"
		for s in sample_shipments:
			shipment_list += f"<li><a href='/app/shipment/{s.name}'>{s.name}</a> (Order ID: {s.shiprocket_order_id})</li>"
		shipment_list += "</ul>"
		
		message = f"""
		<h3>Shiprocket AWB Sync Report</h3>
		<p>
			<strong>Successfully Synced:</strong> {success_count}<br>
			<strong>Pending/Failed:</strong> {failed_count}
		</p>
		<p>
			Some shipments are still waiting for AWB assignment from Shiprocket. 
			This is normal for recently created shipments. If shipments remain without AWB 
			for more than 2 hours, please check Shiprocket dashboard.
		</p>
		<h4>Sample Pending Shipments:</h4>
		{shipment_list}
		<p><em>This is an automated alert from ERPNext Shipping Extended.</em></p>
		"""
		
		frappe.sendmail(
			recipients=recipient_emails,
			subject=f"Shiprocket AWB Sync: {failed_count} Pending",
			message=message,
			delayed=False
		)
		
	except Exception as e:
		frappe.log_error(
			message=f"Error sending AWB sync alert: {str(e)}",
			title="AWB Sync Alert Failed"
		)


@frappe.whitelist()
def sync_awb_manually(shipment_name):
	"""
	Manual AWB sync from UI
	Called from "Sync AWB" button
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
				"message": "AWB not assigned yet by courier. Please try again in a few minutes."
			}
	except Exception as e:
		frappe.log_error(
			message=f"Shipment: {shipment_name}\nError: {str(e)}",
			title="Manual AWB Sync Failed"
		)
		return {"success": False, "message": str(e)}
