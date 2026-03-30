frappe.ui.form.on('Shiprocket Settings', {
	refresh(frm) {
		set_shiprocket_auth_status(frm);

		if (frm.doc.enabled) {
			frm.add_custom_button(__('Copy Webhook URL'), async () => {
				const { message } = await frappe.call({
					method: 'erpnext_shipping_extended.doctype.shiprocket_settings.shiprocket_settings.get_shiprocket_webhook_url',
				});

				if (message) {
					await navigator.clipboard.writeText(message);
					frappe.show_alert({
						message: __('Webhook URL copied'),
						indicator: 'green',
					});
				}
			});
		}
	},
	enabled(frm) {
		set_webhook_url(frm);
		set_shiprocket_auth_status(frm);
	},
	onload(frm) {
		set_webhook_url(frm);
		set_shiprocket_auth_status(frm);
	},
});

function set_webhook_url(frm) {
	if (!frm.doc.enabled) {
		return;
	}

	frappe.call({
		method: 'erpnext_shipping_extended.doctype.shiprocket_settings.shiprocket_settings.get_shiprocket_webhook_url',
		callback: ({ message }) => {
			if (message && frm.get_field('webhook_url') && frm.doc.webhook_url !== message) {
				frm.set_value('webhook_url', message);
			}
		},
	});
}

function set_shiprocket_auth_status(frm) {
	if (!frm.doc.enabled) {
		if (frm.get_field('bearer_token')) {
			frm.set_value('bearer_token', '');
		}
		if (frm.get_field('token_expiry')) {
			frm.set_value('token_expiry', null);
		}
		return;
	}

	frappe.call({
		method: 'erpnext_shipping_extended.doctype.shiprocket_settings.shiprocket_settings.get_shiprocket_auth_status',
		callback: ({ message }) => {
			if (frm.get_field('bearer_token')) {
				frm.set_value('bearer_token', message?.bearer_token || '');
			}
			if (frm.get_field('token_expiry')) {
				frm.set_value('token_expiry', message?.token_expiry || null);
			}
		},
	});
}
