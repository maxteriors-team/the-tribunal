# Warehouse Inventory Tracker

A standalone Google Apps Script web app. It reads product names, SKUs, and prices from a Google Sheet and appends warehouse counts to an inventory log. It does not connect to The Tribunal.

## Sheet setup

1. Create a Google Sheet with a tab named **Products**.
2. Add headers in row 1. Supported headers:
   - SKU: `SKU`, `Item Number`, or `Item #`
   - Product: `Product Name`, `Product`, `Item Name`, or `Description`
   - Price: `Price`, `Unit Price`, or `List Price`
3. Add one product per row. Example:

| SKU | Product Name | Price |
| --- | --- | ---: |
| PW-100 | Pressure washer hose, 100 ft | $129.00 |
| TIP-040 | Rotary turbo nozzle | $74.50 |

The app creates an **Inventory Log** tab on the first save with timestamp, warehouse, counter, SKU, product name, price, and quantity columns.

## Deploy

1. In the Sheet, open **Extensions → Apps Script**.
2. Replace `Code.gs` with this directory's `Code.gs`.
3. Add an HTML file named `Index` and paste in `Index.html`.
4. Open **Project Settings**, enable `appsscript.json`, and replace it with this directory's manifest.
5. Select **Deploy → New deployment → Web app**.
6. Set **Execute as** to yourself. Choose the audience that should be able to submit warehouse counts, then deploy.
7. Authorize access to the Sheet and share the resulting web app URL.

For internal inventory, restrict access to your Google Workspace domain instead of selecting anyone. The deployment owner remains the only identity used to access the Sheet.

## Data behavior

- Product data is read fresh whenever the page loads.
- Entering a warehouse location loads its latest logged quantity for each SKU into the Current column.
- Blank product rows are ignored.
- Only products present in the current catalog can be logged.
- Quantities must be whole numbers from 0 through 999,999.
- Each submission appends rows; previous counts are never overwritten.
- Concurrent saves use a document lock to prevent overlapping writes.

## Tests

Run the focused Apps Script service tests with:

```sh
node --test inventory-tracker/tests/Code.test.js
```

## Customization

Edit `CONFIG` at the top of `Code.gs` to change sheet names or accepted column headers. Edit the `timeZone` value in `appsscript.json` to match the warehouse.
