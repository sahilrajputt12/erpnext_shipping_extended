// Shiprocket Extended Features - UI Integration
// Add buttons for Return, NDR, Pickup, Manifest, POD

frappe.ui.form.on('Shipment', {
	refresh: function(frm) {
		if (frm.doc.service_provider !== 'Shiprocket' || frm.doc.docstatus !== 1) {
			return;
		}

		// 1. CREATE RETURN SHIPMENT
		if (frm.doc.shiprocket_order_id && frm.doc.status === 'Delivered') {
			frm.add_custom_button(__('Create Return'), function() {
				frappe.prompt([
					{
						label: 'Return Reason',
						fieldname: 'return_reason',
						fieldtype: 'Select',
						options: [
							'Defective Product',
							'Wrong Item Delivered',
							'Size/Color Mismatch',
							'Customer Changed Mind',
							'Product Not as Described',
							'Other'
						],
						reqd: 1
					}
				], function(values) {
					frappe.call({
						method: 'erpnext_shipping_extended.api.returns.create_return_shipment',
						args: {
							shipment_name: frm.doc.name,
							return_reason: values.return_reason
						},
						freeze: true,
						freeze_message: __('Creating return shipment...'),
						callback: function(r) {
							if (r.message && r.message.success) {
								frappe.show_alert({
									message: __('Return shipment created: {0}', [r.message.return_shipment]),
									indicator: 'green'
								});
								frappe.set_route('Form', 'Shipment', r.message.return_shipment);
							}
						}
					});
				}, __('Create Return Shipment'), __('Create'));
			}, __('Returns'));
		}

		// 2. NDR ACTIONS (if shipment has NDR status)
		if (frm.doc.tracking_status && frm.doc.tracking_status.toLowerCase().includes('ndr')) {
			frm.add_custom_button(__('Re-attempt Delivery'), function() {
				frappe.prompt([
					{
						label: 'Customer Name',
						fieldname: 'customer_name',
						fieldtype: 'Data'
					},
					{
						label: 'Customer Phone',
						fieldname: 'customer_phone',
						fieldtype: 'Data'
					},
					{
						label: 'Address',
						fieldname: 'address',
						fieldtype: 'Small Text'
					},
					{
						label: 'Pincode',
						fieldname: 'pincode',
						fieldtype: 'Data'
					},
					{
						label: 'Remarks',
						fieldname: 'remarks',
						fieldtype: 'Small Text'
					}
				], function(values) {
					frappe.call({
						method: 'erpnext_shipping_extended.api.ndr.schedule_ndr_reattempt',
						args: {
							shipment_name: frm.doc.name,
							...values
						},
						freeze: true,
						callback: function(r) {
							if (r.message && r.message.success) {
								frappe.show_alert({
									message: __('Re-delivery scheduled'),
									indicator: 'green'
								});
								frm.reload_doc();
							}
						}
					});
				}, __('Schedule Re-delivery'), __('Submit'));
			}, __('NDR Actions'));

			frm.add_custom_button(__('Mark for RTO'), function() {
				frappe.confirm(
					__('Are you sure you want to mark this shipment for Return to Origin?'),
					function() {
						frappe.call({
							method: 'erpnext_shipping_extended.api.ndr.ndr_action',
							args: {
								shipment_name: frm.doc.name,
								action: 'rto'
							},
							callback: function(r) {
								if (r.message && r.message.success) {
									frappe.show_alert({
										message: __('Marked for RTO'),
										indicator: 'orange'
									});
									frm.reload_doc();
								}
							}
						});
					}
				);
			}, __('NDR Actions'));
		}

		// 3. GENERATE PICKUP
		if (frm.doc.shiprocket_shipment_id && frm.doc.status === 'Booked') {
			frm.add_custom_button(__('Generate Pickup'), function() {
				frappe.call({
					method: 'erpnext_shipping_extended.api.pickup.generate_pickup_request',
					args: {
						shipment_name: frm.doc.name,
						pickup_date: frm.doc.pickup_date
					},
					freeze: true,
					freeze_message: __('Generating pickup request...'),
					callback: function(r) {
						if (r.message && r.message.success) {
							frappe.show_alert({
								message: __('Pickup generated. Token: {0}', [r.message.pickup_token]),
								indicator: 'green'
							});
							frm.reload_doc();
						}
					}
				});
			}, __('Pickup'));

			frm.add_custom_button(__('Check Pickup Status'), function() {
				frappe.call({
					method: 'erpnext_shipping_extended.api.pickup.check_pickup_status_by_shipment',
					args: {
						shipment_name: frm.doc.name
					},
					callback: function(r) {
						if (r.message && r.message.success) {
							frappe.msgprint({
								title: __('Pickup Status'),
								message: JSON.stringify(r.message.pickup_data, null, 2),
								indicator: 'blue'
							});
						} else {
							frappe.msgprint(r.message.message);
						}
					}
				});
			}, __('Pickup'));
		}

		// 4. DOWNLOAD POD
		if (frm.doc.awb_number && frm.doc.status === 'Delivered') {
			frm.add_custom_button(__('Download POD'), function() {
				frappe.call({
					method: 'erpnext_shipping_extended.api.manifest.download_pod',
					args: {
						shipment_name: frm.doc.name
					},
					freeze: true,
					freeze_message: __('Downloading Proof of Delivery...'),
					callback: function(r) {
						if (r.message && r.message.success) {
							frappe.show_alert({
								message: __('POD downloaded successfully'),
								indicator: 'green'
							});
							frm.reload_doc();
							
							// Open POD in new tab
							if (r.message.file_url) {
								window.open(r.message.file_url, '_blank');
							}
						}
					}
				});
			}, __('Documents'));

			frm.add_custom_button(__('Download Shipping Invoice'), function() {
				frappe.call({
					method: 'erpnext_shipping_extended.api.manifest.download_shipping_invoice',
					args: {
						shipment_name: frm.doc.name
					},
					freeze: true,
					freeze_message: __('Downloading shipping invoice...'),
					callback: function(r) {
						if (r.message && r.message.success) {
							frappe.show_alert({
								message: __('Invoice downloaded'),
								indicator: 'green'
							});
							frm.reload_doc();
							
							if (r.message.file_url) {
								window.open(r.message.file_url, '_blank');
							}
						}
					}
				});
			}, __('Documents'));
		}

		// 5. SYNC AWB (if missing)
		if (frm.doc.shiprocket_order_id && !frm.doc.awb_number) {
			frm.add_custom_button(__('Sync AWB'), function() {
				frappe.call({
					method: 'erpnext_shipping_extended.api.awb_sync.sync_awb_manually',
					args: {
						shipment_name: frm.doc.name
					},
					callback: function(r) {
						if (r.message && r.message.success && r.message.awb) {
							frappe.show_alert({
								message: __('AWB synced: {0}', [r.message.awb]),
								indicator: 'green'
							});
							frm.reload_doc();
						} else {
							frappe.msgprint(__('AWB not assigned yet. Please try again later.'));
						}
					}
				});
			}, __('Shiprocket'));
		}
	}
});


// BULK OPERATIONS ON SHIPMENT LIST
frappe.listview_settings['Shipment'] = {
	onload: function(listview) {
		// Bulk Manifest Generation
		listview.page.add_action_item(__('Generate Manifest'), function() {
			let selected = listview.get_checked_items();
			
			if (selected.length === 0) {
				frappe.msgprint(__('Please select shipments'));
				return;
			}
			
			let shipment_names = selected.map(item => item.name);
			
			frappe.call({
				method: 'erpnext_shipping_extended.api.manifest.generate_manifest_for_shipments',
				args: {
					shipment_names: shipment_names
				},
				freeze: true,
				freeze_message: __('Generating manifest...'),
				callback: function(r) {
					if (r.message && r.message.success) {
						frappe.show_alert({
							message: __('Manifest generated for {0} shipments', [r.message.shipment_count]),
							indicator: 'green'
						});
						
						if (r.message.file_url) {
							window.open(r.message.file_url, '_blank');
						}
					}
				}
			});
		});

		// Bulk Pickup Generation
		listview.page.add_action_item(__('Generate Pickups'), function() {
			let selected = listview.get_checked_items();
			
			if (selected.length === 0) {
				frappe.msgprint(__('Please select shipments'));
				return;
			}
			
			let shipment_names = selected.map(item => item.name);
			
			frappe.prompt({
				label: 'Pickup Date',
				fieldname: 'pickup_date',
				fieldtype: 'Date',
				default: frappe.datetime.get_today()
			}, function(values) {
				frappe.call({
					method: 'erpnext_shipping_extended.api.pickup.bulk_generate_pickups',
					args: {
						shipment_names: shipment_names,
						pickup_date: values.pickup_date
					},
					freeze: true,
					callback: function(r) {
						if (r.message && r.message.success) {
							frappe.show_alert({
								message: __('Pickup generated'),
								indicator: 'green'
							});
							listview.refresh();
						}
					}
				});
			}, __('Select Pickup Date'), __('Generate'));
		});

		// Bulk POD Download
		listview.page.add_action_item(__('Download PODs'), function() {
			let selected = listview.get_checked_items();
			
			if (selected.length === 0) {
				frappe.msgprint(__('Please select shipments'));
				return;
			}
			
			let shipment_names = selected.map(item => item.name);
			
			frappe.call({
				method: 'erpnext_shipping_extended.api.manifest.bulk_download_pods',
				args: {
					shipment_names: shipment_names
				},
				freeze: true,
				freeze_message: __('Downloading PODs...'),
				callback: function(r) {
					if (r.message) {
						frappe.msgprint({
							title: __('POD Download Results'),
							message: __('Success: {0}, Failed: {1}', 
								[r.message.success_count, r.message.failed_count]),
							indicator: 'blue'
						});
					}
				}
			});
		});

		// Sync NDR Shipments
		listview.page.add_action_item(__('Sync NDR Shipments'), function() {
			frappe.call({
				method: 'erpnext_shipping_extended.api.ndr.sync_ndr_shipments',
				freeze: true,
				freeze_message: __('Syncing NDR shipments from Shiprocket...'),
				callback: function(r) {
					if (r.message && r.message.success) {
						frappe.msgprint({
							title: __('NDR Sync Complete'),
							message: __('Found {0} NDR shipments, synced {1}', 
								[r.message.ndr_count, r.message.synced_count]),
							indicator: 'green'
						});
						listview.refresh();
					}
				}
			});
		});
	}
};
