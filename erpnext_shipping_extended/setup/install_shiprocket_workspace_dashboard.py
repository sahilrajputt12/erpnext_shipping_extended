from __future__ import annotations

import frappe
import json
from frappe.utils.dashboard import sync_dashboards


def execute() -> None:
	"""Create ShipRocket dashboard charts, number cards, dashboard, and workspace for this app."""
	_create_dashboard_charts()
	_create_number_cards()
	_create_dashboard()
	_create_workspace()
	sync_dashboards("erpnext_shipping_extended")
	frappe.clear_cache()
	frappe.db.commit()


def _create_dashboard_charts() -> None:
	"""Create all dashboard charts referenced by the workspace."""
	charts = [
		{
			"doctype": "Dashboard Chart",
			"chart_name": "Shipment Status Overview",
			"chart_type": "Donut",
			"document_type": "Shipment",
			"filters_json": json.dumps({"docstatus": ["=", 1]}),
			"group_by_based_on": "status",
			"group_by_type": "Count",
			"is_public": 1,
			"is_standard": 1,
			"module": "ERPNext Shipping Extended",
			"type": "Group By",
			"timeseries": 0,
			"timespan": "Last Month",
			"based_on": "creation",
		},
		{
			"doctype": "Dashboard Chart",
			"chart_name": "Courier Performance",
			"chart_type": "Bar",
			"document_type": "Shipment",
			"filters_json": json.dumps({"docstatus": ["=", 1]}),
			"group_by_based_on": "carrier",
			"group_by_type": "Count",
			"is_public": 1,
			"is_standard": 1,
			"module": "ERPNext Shipping Extended",
			"number_of_groups": 10,
			"type": "Group By",
			"timeseries": 0,
			"timespan": "Last Month",
			"based_on": "creation",
		},
		{
			"doctype": "Dashboard Chart",
			"chart_name": "Monthly Shipment Trends",
			"chart_type": "Line",
			"document_type": "Shipment",
			"filters_json": json.dumps({"docstatus": ["=", 1]}),
			"is_public": 1,
			"is_standard": 1,
			"module": "ERPNext Shipping Extended",
			"time_interval": "Monthly",
			"timeseries": 1,
			"timespan": "Last Year",
			"type": "Count",
			"value_based_on": "creation",
			"based_on": "creation",
		},
	]
	for chart_data in charts:
		if not frappe.db.exists("Dashboard Chart", chart_data["chart_name"]):
			doc = frappe.get_doc(chart_data)
			doc.insert(ignore_permissions=True)


def _create_number_cards() -> None:
	"""Create all number cards referenced by the workspace."""
	cards = [
		{
			"doctype": "Number Card",
			"label": "Active Shipments",
			"document_type": "Shipment",
			"function": "Count",
			"filters_json": json.dumps({"docstatus": ["=", 1], "status": ["=", "Submitted"]}),
			"is_public": 1,
			"show_percentage_stats": 1,
			"stats_time_interval": "Daily",
		},
		{
			"doctype": "Number Card",
			"label": "Delivered Today",
			"document_type": "Shipment",
			"function": "Count",
			"filters_json": json.dumps({"docstatus": ["=", 1], "status": ["=", "Delivered"]}),
			"is_public": 1,
			"show_percentage_stats": 1,
			"stats_time_interval": "Daily",
		},
		{
			"doctype": "Number Card",
			"label": "In Transit",
			"document_type": "Shipment",
			"function": "Count",
			"filters_json": json.dumps({"docstatus": ["=", 1], "status": ["in", ["In Transit", "Shipped"]]}),
			"is_public": 1,
			"show_percentage_stats": 1,
			"stats_time_interval": "Daily",
		},
		{
			"doctype": "Number Card",
			"label": "Exception Shipments",
			"document_type": "Shipment",
			"function": "Count",
			"filters_json": json.dumps({"docstatus": ["=", 1], "status": ["in", ["Failed", "Cancelled", "Lost"]]}),
			"is_public": 1,
			"show_percentage_stats": 1,
			"stats_time_interval": "Daily",
		},
		{
			"doctype": "Number Card",
			"label": "Total Shipping Cost",
			"document_type": "Shipment",
			"function": "Sum",
			"aggregate_function_based_on": "grand_total",
			"filters_json": json.dumps({"docstatus": ["=", 1]}),
			"is_public": 1,
			"show_percentage_stats": 1,
			"stats_time_interval": "Monthly",
		},
		{
			"doctype": "Number Card",
			"label": "Pending Delivery Notes",
			"document_type": "Delivery Note",
			"function": "Count",
			"filters_json": json.dumps({"docstatus": ["=", 1], "per_billed": ["<", 100]}),
			"is_public": 1,
			"show_percentage_stats": 1,
			"stats_time_interval": "Daily",
		},
	]
	for card_data in cards:
		if not frappe.db.exists("Number Card", card_data["label"]):
			doc = frappe.get_doc(card_data)
			doc.insert(ignore_permissions=True)


def _create_dashboard() -> None:
	"""Create the ShipRocket dashboard."""
	if frappe.db.exists("Dashboard", "ShipRocket"):
		return
	dashboard = frappe.get_doc({
		"doctype": "Dashboard",
		"dashboard_name": "ShipRocket",
		"module": "ERPNext Shipping Extended",
		"is_standard": 1,
		"charts": [
			{"chart": "Shipment Status Overview", "width": "Half"},
			{"chart": "Courier Performance", "width": "Half"},
			{"chart": "Monthly Shipment Trends", "width": "Full"},
		],
		"number_cards": [
			{"label": "Active Shipments"},
			{"label": "Delivered Today"},
			{"label": "In Transit"},
			{"label": "Exception Shipments"},
			{"label": "Total Shipping Cost"},
			{"label": "Pending Delivery Notes"},
		],
	})
	dashboard.insert(ignore_permissions=True)


def _create_workspace() -> None:
	"""Create the ShipRocket workspace using core APIs."""
	if frappe.db.exists("Workspace", "ShipRocket"):
		return
	workspace = frappe.get_doc({
		"doctype": "Workspace",
		"name": "ShipRocket",
		"title": "ShipRocket",
		"label": "ShipRocket",
		"module": "ERPNext Shipping Extended",
		"category": "Modules",
		"icon": "truck",
		"public": 1,
		"sequence_id": 20,
		"charts": [
			{"chart_name": "Shipment Status Overview", "label": "Shipment Status Overview"},
			{"chart_name": "Courier Performance", "label": "Courier Performance"},
			{"chart_name": "Monthly Shipment Trends", "label": "Monthly Shipment Trends"},
		],
		"number_cards": [
			{"label": "Active Shipments", "number_card_name": "Active Shipments"},
			{"label": "Delivered Today", "number_card_name": "Delivered Today"},
			{"label": "In Transit", "number_card_name": "In Transit"},
			{"label": "Exception Shipments", "number_card_name": "Exception Shipments"},
			{"label": "Total Shipping Cost", "number_card_name": "Total Shipping Cost"},
			{"label": "Pending Delivery Notes", "number_card_name": "Pending Delivery Notes"},
		],
		"links": [
			{"type": "Card Break", "label": "Shipment Management"},
			{"type": "Link", "link_type": "DocType", "link_to": "Shipment", "label": "Shipment", "onboard": 1},
			{"type": "Link", "link_type": "DocType", "link_to": "Delivery Note", "label": "Delivery Note"},
			{"type": "Link", "link_type": "DocType", "link_to": "Parcel Service Type", "label": "Parcel Service Type"},
			{"type": "Card Break", "label": "Shipping Operations"},
			{"type": "Link", "link_type": "DocType", "link_to": "Shipment", "label": "Booked Shipments"},
			{"type": "Link", "link_type": "DocType", "link_to": "Shipment", "label": "In Transit Shipments"},
			{"type": "Link", "link_type": "DocType", "link_to": "Shipment", "label": "Delivered Shipments"},
			{"type": "Card Break", "label": "Configuration"},
			{"type": "Link", "link_type": "DocType", "link_to": "Shiprocket Settings", "label": "Shiprocket Settings", "onboard": 1},
			{"type": "Link", "link_type": "DocType", "link_to": "Shipment Parcel Template", "label": "Shipment Parcel Template"},
			{"type": "Link", "link_type": "DocType", "link_to": "Shipping Rule", "label": "Shipping Rule"},
			{"type": "Link", "link_type": "DocType", "link_to": "Parcel Service", "label": "Parcel Service"},
		],
		"shortcuts": [
			{"type": "DocType", "link_to": "Shipment", "label": "Shipment", "color": "Blue", "format": "{} Active", "stats_filter": '{"docstatus":1,"status":"Booked"}'},
			{"type": "DocType", "link_to": "Shiprocket Settings", "label": "Shiprocket Settings", "color": "Green", "format": "{} Ready"},
			{"type": "DocType", "link_to": "Delivery Note", "label": "Delivery Note", "color": "Orange", "format": "{} To Bill", "stats_filter": '{"docstatus":1,"status":"To Bill"}'},
			{"type": "Dashboard", "link_to": "ShipRocket", "label": "ShipRocket Dashboard", "color": "Purple"},
		],
	})
	workspace.insert(ignore_permissions=True)
