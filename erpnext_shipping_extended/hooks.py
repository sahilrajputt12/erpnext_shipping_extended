app_name = "erpnext_shipping_extended"
app_title = "ERPNext Shipping Extended"
app_publisher = "AI Spark Tech"
app_description = "Shiprocket integration for ERPNext Shipping (provider-based extension)"
app_email = "support@aisparktech.in"
app_license = "unlicense"

# Apps
# ------------------

# required_apps = []

# Each item in the list will be shown as an app in the apps page
# add_to_apps_screen = [
# 	{
# 		"name": "erpnext_shipping_extended",
# 		"logo": "/assets/erpnext_shipping_extended/logo.png",
# 		"title": "ERPNext Shipping Extended",
# 		"route": "/erpnext_shipping_extended",
# 		"has_permission": "erpnext_shipping_extended.api.permission.has_app_permission"
# 	}
# ]

# Includes in <head>
# ------------------

# include js, css files in header of desk.html
# app_include_css = "/assets/erpnext_shipping_extended/css/erpnext_shipping_extended.css"
# app_include_js = "/assets/erpnext_shipping_extended/js/erpnext_shipping_extended.js"

# include js, css files in header of web template
# web_include_css = "/assets/erpnext_shipping_extended/css/erpnext_shipping_extended.css"
# web_include_js = "/assets/erpnext_shipping_extended/js/erpnext_shipping_extended.js"

# include custom scss in every website theme (without file extension ".scss")
# website_theme_scss = "erpnext_shipping_extended/public/scss/website"

# include js, css files in header of web form
# webform_include_js = {"doctype": "public/js/doctype.js"}
# webform_include_css = {"doctype": "public/css/doctype.css"}

# include js in page
# page_js = {"page" : "public/js/file.js"}

# include js in doctype views
# NOTE: This app doesn't need extra Shipment JS; avoid overriding core `erpnext_shipping` behavior.
# doctype_js = {"doctype" : "public/js/doctype.js"}
doctype_js = {
    "Shipment": "public/js/shipment_extended.js",
    "Shiprocket Settings": "doctype/shiprocket_settings/shiprocket_settings.js",
}
doctype_list_js = {"doctype" : "public/js/doctype_list.js"}
# doctype_tree_js = {"doctype" : "public/js/doctype_tree.js"}
# doctype_calendar_js = {"doctype" : "public/js/doctype_calendar.js"}

# Svg Icons
# ------------------
# include app icons in desk
# app_include_icons = "erpnext_shipping_extended/public/icons.svg"

# Home Pages
# ----------

# application home page (will override Website Settings)
# home_page = "login"

# website user home page (by Role)
# role_home_page = {
# 	"Role": "home_page"
# }

# Generators
# ----------

# automatically create page for each record of this doctype
# website_generators = ["Web Page"]

# Jinja
# ----------

# add methods and filters to jinja environment
# jinja = {
# 	"methods": "erpnext_shipping_extended.utils.jinja_methods",
# 	"filters": "erpnext_shipping_extended.utils.jinja_filters"
# }

# Installation
# ------------

# before_install = "erpnext_shipping_extended.install.before_install"
after_install = "erpnext_shipping_extended.install.after_install"

# Uninstallation
# ------------

# before_uninstall = "erpnext_shipping_extended.uninstall.before_uninstall"
# after_uninstall = "erpnext_shipping_extended.uninstall.after_uninstall"

# Integration Setup
# ------------------
# To set up dependencies/integrations with other apps
# Name of the app being installed is passed as an argument

# before_app_install = "erpnext_shipping_extended.utils.before_app_install"
# after_app_install = "erpnext_shipping_extended.utils.after_app_install"

# Integration Cleanup
# -------------------
# To clean up dependencies/integrations with other apps
# Name of the app being uninstalled is passed as an argument

# before_app_uninstall = "erpnext_shipping_extended.utils.before_app_uninstall"
# after_app_uninstall = "erpnext_shipping_extended.utils.after_app_uninstall"

# Desk Notifications
# ------------------
# See frappe.core.notifications.get_notification_config

# notification_config = "erpnext_shipping_extended.notifications.get_notification_config"

# Permissions
# -----------
# Permissions evaluated in scripted ways

# permission_query_conditions = {
# 	"Event": "frappe.desk.doctype.event.event.get_permission_query_conditions",
# }
#
# has_permission = {
# 	"Event": "frappe.desk.doctype.event.event.has_permission",
# }

# DocType Class
# ---------------
# Override standard doctype classes

# override_doctype_class = {
# 	"ToDo": "custom_app.overrides.CustomToDo"
# }

# Document Events
# ---------------
# Hook on document methods and events

doc_events = {
	"Shipment": {
		"validate": "erpnext_shipping_extended.utils.validate_shiprocket_shipment",
		"before_submit": "erpnext_shipping_extended.utils.validate_shiprocket_shipment",
		"on_cancel": "erpnext_shipping_extended.api.shipping_extended.on_shipment_cancel",
	}
}

# Scheduled Tasks
# ---------------

scheduler_events = {
	"daily": [
		"erpnext_shipping_extended.tasks.update_tracking_daily"
	],
	"hourly": [
		"erpnext_shipping_extended.tasks.sync_pending_awbs"
	],
}

# Testing
# -------

# before_tests = "erpnext_shipping_extended.install.before_tests"

# Overriding Methods
# ------------------------------
#
override_whitelisted_methods = {
	# These are the exact whitelisted method paths called by `erpnext_shipping`'s Shipment form JS.
	"erpnext_shipping.erpnext_shipping.shipping.fetch_shipping_rates": "erpnext_shipping_extended.api.shipping_extended.fetch_shipping_rates",
	"erpnext_shipping.erpnext_shipping.shipping.create_shipment": "erpnext_shipping_extended.api.shipping_extended.create_shipment",
	"erpnext_shipping.erpnext_shipping.shipping.print_shipping_label": "erpnext_shipping_extended.api.shipping_extended.print_shipping_label",
	"erpnext_shipping.erpnext_shipping.shipping.update_tracking": "erpnext_shipping_extended.api.shipping_extended.update_tracking",
	"erpnext_shipping_extended.api.webhook.shiprocket_webhook": "erpnext_shipping_extended.api.webhook.shiprocket_webhook"
}

# each overriding function accepts a `data` argument;
# generated from the base implementation of the doctype dashboard,
# along with any modifications made in other Frappe apps
# override_doctype_dashboards = {
# 	"Task": "erpnext_shipping_extended.task.get_dashboard_data"
# }

# exempt linked doctypes from being automatically cancelled
#
# auto_cancel_exempted_doctypes = ["Auto Repeat"]

# Ignore links to specified DocTypes when deleting documents
# -----------------------------------------------------------

# ignore_links_on_delete = ["Communication", "ToDo"]

# Request Events
# ----------------
# before_request = ["erpnext_shipping_extended.utils.before_request"]
# after_request = ["erpnext_shipping_extended.utils.after_request"]

# Job Events
# ----------
# before_job = ["erpnext_shipping_extended.utils.before_job"]
# after_job = ["erpnext_shipping_extended.utils.after_job"]

# User Data Protection
# --------------------

# user_data_fields = [
# 	{
# 		"doctype": "{doctype_1}",
# 		"filter_by": "{filter_by}",
# 		"redact_fields": ["{field_1}", "{field_2}"],
# 		"partial": 1,
# 	},
# 	{
# 		"doctype": "{doctype_2}",
# 		"filter_by": "{filter_by}",
# 		"partial": 1,
# 	},
# 	{
# 		"doctype": "{doctype_3}",
# 		"strict": False,
# 	},
# 	{
# 		"doctype": "{doctype_4}"
# 	}
# ]

# Authentication and authorization
# --------------------------------

# auth_hooks = [
# 	"erpnext_shipping_extended.auth.validate"
# ]

# Automatically update python controller files with type annotations for this app.
# export_python_type_annotations = True

# default_log_clearing_doctypes = {
# 	"Logging DocType Name": 30  # days to retain logs
# }

# Translation
# ------------
# List of apps whose translatable strings should be excluded from this app's translations.
# ignore_translatable_strings_from = []
