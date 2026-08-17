const CONFIG = Object.freeze({
  productsSheet: 'Products',
  logSheet: 'Inventory Log',
  headers: {
    sku: ['sku', 'item number', 'item #'],
    name: ['product name', 'product', 'item name', 'description'],
    price: ['price', 'unit price', 'list price'],
  },
});

function doGet() {
  return HtmlService.createTemplateFromFile('Index')
    .evaluate()
    .setTitle('Warehouse Inventory')
    .addMetaTag('viewport', 'width=device-width, initial-scale=1');
}

function getCatalog() {
  const sheet = getRequiredSheet_(CONFIG.productsSheet);
  const values = sheet.getDataRange().getDisplayValues();

  if (values.length < 2) {
    return { products: [], lastUpdated: new Date().toISOString() };
  }

  const headerIndexes = findHeaderIndexes_(values[0]);
  const products = values.slice(1)
    .map((row) => ({
      sku: row[headerIndexes.sku].trim(),
      name: row[headerIndexes.name].trim(),
      price: row[headerIndexes.price].trim(),
    }))
    .filter((product) => product.sku && product.name);

  return { products, lastUpdated: new Date().toISOString() };
}

function getStockLevels(locationValue) {
  const location = cleanText_(locationValue, 100);
  if (!location) {
    return {};
  }

  const spreadsheet = SpreadsheetApp.getActiveSpreadsheet();
  const sheet = spreadsheet.getSheetByName(CONFIG.logSheet);
  if (!sheet || sheet.getLastRow() < 2) {
    return {};
  }

  const values = sheet.getDataRange().getValues();
  const levels = {};
  values.slice(1).forEach((row) => {
    const rowLocation = cleanText_(row[1], 100);
    const sku = cleanText_(row[3], 100);
    const quantity = Number(row[6]);
    if (rowLocation.toLowerCase() === location.toLowerCase() && sku && Number.isInteger(quantity) && quantity >= 0) {
      levels[sku] = quantity;
    }
  });
  return levels;
}

function saveInventory(payload) {
  if (!payload || !Array.isArray(payload.items)) {
    throw new Error('Inventory items are required.');
  }

  const location = cleanText_(payload.location, 100);
  const countedBy = cleanText_(payload.countedBy, 100);
  if (!location || !countedBy) {
    throw new Error('Warehouse location and counter name are required.');
  }

  const catalog = getCatalog().products;
  const catalogBySku = new Map(catalog.map((product) => [product.sku, product]));
  const submittedAt = new Date();
  const rows = payload.items.map((item) => {
    const sku = cleanText_(item.sku, 100);
    const product = catalogBySku.get(sku);
    const quantity = Number(item.quantity);

    if (!product || !Number.isInteger(quantity) || quantity < 0 || quantity > 999999) {
      throw new Error(`Invalid inventory count for SKU ${sku || 'unknown'}.`);
    }

    return [submittedAt, location, countedBy, product.sku, product.name, product.price, quantity];
  });

  if (!rows.length) {
    throw new Error('Enter at least one inventory count.');
  }

  const lock = LockService.getDocumentLock();
  lock.waitLock(30000);
  try {
    const sheet = getOrCreateLogSheet_();
    sheet.getRange(sheet.getLastRow() + 1, 1, rows.length, rows[0].length).setValues(rows);
  } finally {
    lock.releaseLock();
  }

  return { saved: rows.length, submittedAt: submittedAt.toISOString() };
}

function getRequiredSheet_(name) {
  const sheet = SpreadsheetApp.getActiveSpreadsheet().getSheetByName(name);
  if (!sheet) {
    throw new Error(`Missing required sheet: ${name}.`);
  }
  return sheet;
}

function getOrCreateLogSheet_() {
  const spreadsheet = SpreadsheetApp.getActiveSpreadsheet();
  let sheet = spreadsheet.getSheetByName(CONFIG.logSheet);
  if (!sheet) {
    sheet = spreadsheet.insertSheet(CONFIG.logSheet);
    sheet.appendRow(['Timestamp', 'Warehouse', 'Counted By', 'SKU', 'Product Name', 'Price', 'Quantity']);
    sheet.setFrozenRows(1);
  }
  return sheet;
}

function findHeaderIndexes_(headerRow) {
  const normalized = headerRow.map((header) => String(header).trim().toLowerCase());
  return Object.fromEntries(Object.entries(CONFIG.headers).map(([key, aliases]) => {
    const index = normalized.findIndex((header) => aliases.includes(header));
    if (index === -1) {
      throw new Error(`Products sheet is missing a ${key} column.`);
    }
    return [key, index];
  }));
}

function cleanText_(value, maxLength) {
  return String(value || '').trim().slice(0, maxLength);
}
