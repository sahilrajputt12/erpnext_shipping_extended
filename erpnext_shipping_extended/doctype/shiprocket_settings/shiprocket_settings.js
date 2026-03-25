frappe.ui.form.on('Shiprocket Settings', {
	refresh(frm) {
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
	},
	onload(frm) {
		set_webhook_url(frm);
	},
});

function set_webhook_url(frm) {
	if (!frm.doc.enabled) {
		return;
	}

	frappe.call({
		method: 'erpnext_shipping_extended.doctype.shiprocket_settings.shiprocket_settings.get_shiprocket_webhook_url',
		callback: ({ message }) => {
			if (message && frm.doc.webhook_url !== message) {
				frm.set_value('webhook_url', message);
			}
		},
	});
}
