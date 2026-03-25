# Architecture

## Goal

Extend `erpnext_shipping` without modifying it by using Frappe hooks and a provider registry.

## Key pieces

- `BaseShippingProvider`:
  - `erpnext_shipping_extended/providers/base_provider.py`
- Provider registry:
  - `erpnext_shipping_extended/providers/registry.py`
- Shiprocket provider:
  - `erpnext_shipping_extended/providers/shiprocket.py`

## Hooking strategy

We override `erpnext_shipping` whitelisted methods via `override_whitelisted_methods`:

- `erpnext_shipping.api.fetch_shipping_rates`
- `erpnext_shipping.api.create_shipment`
- `erpnext_shipping.api.print_shipping_label`
- `erpnext_shipping.api.update_tracking`

Implementation lives in:

- `erpnext_shipping_extended/api/shipping_extended.py`

For non-Shiprocket providers, we delegate back to `erpnext_shipping`.

## Extending with new providers

1. Add a new provider class implementing `BaseShippingProvider`
2. Register it in `_PROVIDER_REGISTRY` (or call `register_provider()`)
3. Add a new Single Settings DocType for the provider
4. Extend `api/shipping_extended.py` to include rate aggregation and provider routing
