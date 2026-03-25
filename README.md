# ERPNext Shipping Extended

Provider-based extension for `erpnext_shipping` adding **Shiprocket** integration (rates, booking, labels, tracking) without modifying core apps.

## Compatibility

- ERPNext v13, v14, v15
- Works even if `erpnext_shipping` is missing (Shiprocket-only features will still work where applicable)

## Installation

From your bench:

```bash
bench get-app <your_repo_url>
bench --site <site> install-app erpnext_shipping_extended
bench --site <site> migrate
```

## Setup

1. Go to:
   `Shiprocket Settings`
2. Enable and set:
   - `email`
   - `password`
   - `test_mode`

## Usage

1. Create a `Shipment`
2. Click `Fetch Shipping Rates` (Shiprocket rates will appear alongside existing providers)
3. Select a Shiprocket courier
4. Click `Create Shipment`
5. Click `Print Shipping Label`
6. Tracking updates run daily via scheduler

## Architecture

- Provider interface: `erpnext_shipping_extended.providers.base_provider.BaseShippingProvider`
- Provider registry: `erpnext_shipping_extended.providers.registry`
- Shiprocket implementation: `erpnext_shipping_extended.providers.shiprocket.ShiprocketProvider`

## Security Notes

- Shiprocket password is stored using Frappe `Password` field encryption
- API tokens are cached **in memory only** (not stored in DB)

# erpnext_shipping_extended
