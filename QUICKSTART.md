# QUICKSTART (10 minutes)

## 1) Install

```bash
bench get-app <repo_url>
bench --site <site> install-app erpnext_shipping_extended
bench --site <site> migrate
```

## 2) Configure Shiprocket

1. Open `Shiprocket Settings`
2. Tick `Enabled`
3. Set `Email` + `Password`
4. Save

## 3) Create Shipment

1. Create a `Shipment`
2. Set pickup + delivery addresses and add at least one parcel row
3. Submit the Shipment
4. Click `Fetch Shipping Rates`
5. Select any Shiprocket courier

## 4) Label + Tracking

- Click `Print Shipping Label`
- Tracking updates:
  - Click `Update Tracking` manually
  - Or wait for daily scheduler
