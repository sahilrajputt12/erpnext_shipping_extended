from __future__ import annotations

import frappe


def execute():
	"""Add custom fields required by erpnext_shipping_extended."""
	_create_module_if_missing()
	_create_custom_fields()


def _create_module_if_missing():
	# In Frappe, module is a DocType record in "Module Def".
	module_name = "ERPNext Shipping Extended"
	if frappe.db.exists("Module Def", module_name):
		return

	try:
		doc = frappe.get_doc(
			{
				"doctype": "Module Def",
				"module_name": module_name,
				"app_name": "erpnext_shipping_extended",
				"custom": 1,
			}
		)
		doc.insert(ignore_permissions=True)
		frappe.db.commit()
	except Exception:
		frappe.log_error(title="ERPNext Shipping Extended: module creation failed")


def _create_custom_fields():
	try:
		from frappe.custom.doctype.custom_field.custom_field import create_custom_fields
	except Exception:
		frappe.log_error(title="ERPNext Shipping Extended: create_custom_fields import failed")
		return

	custom_fields = {
		"Shipment": [
			{
				"fieldname": "shiprocket_section",
				"label": "Shiprocket Details",
				"fieldtype": "Section Break",
				"insert_after": "shipment_id",
				"collapsible": 1,
			},
			{
				"fieldname": "shiprocket_shipment_id",
				"label": "Shiprocket Shipment ID",
				"fieldtype": "Data",
				"read_only": 1,
				"insert_after": "shiprocket_section",
			},
			{
				"fieldname": "shiprocket_order_id",
				"label": "Shiprocket Order ID",
				"fieldtype": "Data",
				"read_only": 1,
				"insert_after": "shiprocket_shipment_id",
			},
			{
				"fieldname": "column_break_shiprocket",
				"fieldtype": "Column Break",
				"insert_after": "shiprocket_order_id",
			},
			{
				"fieldname": "extended_provider_data",
				"label": "Extended Provider Data",
				"fieldtype": "Code",
				"options": "JSON",
				"hidden": 1,
				"insert_after": "column_break_shiprocket",
			},
			# Payment related fields
			{
				"fieldname": "payment_section",
				"label": "Payment Details",
				"fieldtype": "Section Break",
				"insert_after": "value_of_goods",
				"collapsible": 1,
			},
			{
				"fieldname": "payment_type",
				"label": "Payment Type",
				"fieldtype": "Select",
				"options": "Prepaid\nCash\nCOD",
				"default": "Prepaid",
				"insert_after": "payment_section",
			},
			{
				"fieldname": "is_cod",
				"label": "Is COD",
				"fieldtype": "Check",
				"default": 0,
				"depends_on": "eval:doc.payment_type=='COD' || doc.payment_type=='Cash'",
				"insert_after": "payment_type",
			},
			{
				"fieldname": "cod_amount",
				"label": "COD Amount",
				"fieldtype": "Currency",
				"depends_on": "eval:doc.is_cod==1",
				"insert_after": "is_cod",
				"read_only": 0,
			},
		]
	}

	try:
		create_custom_fields(custom_fields, ignore_validate=True)
		frappe.db.commit()
		print("✓ Custom fields created successfully")
	except Exception as e:
		frappe.log_error(
			message=f"Error: {str(e)}", 
			title="ERPNext Shipping Extended: custom field creation failed"
		)
		print(f"✗ Custom field creation failed: {str(e)}")
