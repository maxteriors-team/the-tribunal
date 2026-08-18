const assert = require('node:assert/strict');
const fs = require('node:fs');
const test = require('node:test');
const vm = require('node:vm');

function makeSheet({ displayValues = [], values = displayValues, lastRow = values.length } = {}) {
  const writes = [];
  let currentLastRow = lastRow;
  return {
    writes,
    appended: [],
    frozenRows: null,
    getDataRange() {
      return {
        getDisplayValues: () => displayValues,
        getValues: () => values,
      };
    },
    getLastRow: () => currentLastRow,
    getRange(row, column, rowCount, columnCount) {
      return {
        setValues(data) { writes.push({ row, column, rowCount, columnCount, data }); currentLastRow = Math.max(currentLastRow, row + rowCount - 1); },
      };
    },
    appendRow(row) { this.appended.push(row); currentLastRow += 1; },
    setFrozenRows(count) { this.frozenRows = count; },
  };
}

function loadApp(initialSheets = {}) {
  const sheets = { ...initialSheets };
  const lockEvents = [];
  const spreadsheet = {
    getSheetByName: (name) => sheets[name] || null,
    insertSheet(name) {
      const sheet = makeSheet({ lastRow: 0 });
      sheets[name] = sheet;
      return sheet;
    },
  };
  const context = {
    console,
    Date,
    Map,
    Object,
    String,
    Number,
    Error,
    SpreadsheetApp: { getActiveSpreadsheet: () => spreadsheet },
    LockService: {
      getDocumentLock: () => ({
        waitLock(milliseconds) { lockEvents.push(['wait', milliseconds]); },
        releaseLock() { lockEvents.push(['release']); },
      }),
    },
    HtmlService: {},
  };
  vm.createContext(context);
  vm.runInContext(fs.readFileSync('inventory-tracker/Code.gs', 'utf8'), context, { filename: 'Code.gs' });
  return { context, sheets, lockEvents };
}

test('getCatalog creates an empty Products sheet on first use', () => {
  const { context, sheets, lockEvents } = loadApp();

  const result = context.getCatalog();

  assert.deepEqual(JSON.parse(JSON.stringify(result.products)), []);
  assert.deepEqual(JSON.parse(JSON.stringify(sheets.Products.appended[0])), ['SKU', 'Product Name', 'Price']);
  assert.equal(sheets.Products.frozenRows, 1);
  assert.deepEqual(lockEvents, [['wait', 30000], ['release']]);
});

test('getCatalog maps accepted headers and ignores incomplete rows', () => {
  const products = makeSheet({
    displayValues: [
      ['Item #', 'Description', 'List Price'],
      ['SKU-1', 'Surface cleaner', '$129.00'],
      ['', 'Blank SKU', '$2.00'],
      ['SKU-2', 'Hose reel', '$88.50'],
    ],
  });
  const { context } = loadApp({ Products: products });

  const result = context.getCatalog();

  assert.deepEqual(JSON.parse(JSON.stringify(result.products)), [
    { sku: 'SKU-1', name: 'Surface cleaner', price: '$129.00' },
    { sku: 'SKU-2', name: 'Hose reel', price: '$88.50' },
  ]);
  assert.match(result.lastUpdated, /^\d{4}-\d{2}-\d{2}T/);
});

test('getCatalog reports a missing required catalog column', () => {
  const products = makeSheet({ displayValues: [['SKU', 'Product Name'], ['A', 'Item']] });
  const { context } = loadApp({ Products: products });
  assert.throws(() => context.getCatalog(), /missing a price column/);
});

test('getStockLevels loads the latest valid quantity for one warehouse', () => {
  const log = makeSheet({
    values: [
      ['Timestamp', 'Warehouse', 'Counted By', 'SKU', 'Product Name', 'Price', 'Quantity'],
      [new Date('2026-01-01'), 'North', 'A', 'SKU-1', 'Cleaner', '$1', 4],
      [new Date('2026-01-02'), 'South', 'B', 'SKU-1', 'Cleaner', '$1', 50],
      [new Date('2026-01-03'), 'north', 'C', 'SKU-1', 'Cleaner', '$1', 7],
      [new Date('2026-01-03'), 'North', 'C', 'SKU-2', 'Hose', '$2', 0],
      [new Date('2026-01-03'), 'North', 'C', 'SKU-3', 'Bad', '$2', -1],
    ],
  });
  const { context } = loadApp({ 'Inventory Log': log });

  assert.deepEqual(JSON.parse(JSON.stringify(context.getStockLevels(' North '))), { 'SKU-1': 7, 'SKU-2': 0 });
  assert.deepEqual(JSON.parse(JSON.stringify(context.getStockLevels(''))), {});
});

test('saveInventory validates required fields, catalog SKUs, and whole quantities', () => {
  const products = makeSheet({ displayValues: [['SKU', 'Product Name', 'Price'], ['SKU-1', 'Cleaner', '$1']] });
  const { context } = loadApp({ Products: products });

  assert.throws(() => context.saveInventory({ items: [] }), /location and counter name/);
  assert.throws(() => context.saveInventory({ location: 'North', countedBy: 'Sam', items: [] }), /at least one/);
  assert.throws(() => context.saveInventory({ location: 'North', countedBy: 'Sam', items: [{ sku: 'BAD', quantity: 2 }] }), /Invalid inventory count/);
  assert.throws(() => context.saveInventory({ location: 'North', countedBy: 'Sam', items: [{ sku: 'SKU-1', quantity: 1.5 }] }), /Invalid inventory count/);
});

test('saveInventory creates the log and appends normalized catalog rows under a lock', () => {
  const products = makeSheet({ displayValues: [['SKU', 'Product Name', 'Price'], ['SKU-1', 'Cleaner', '$129']] });
  const { context, sheets, lockEvents } = loadApp({ Products: products });

  const result = context.saveInventory({
    location: ' North Warehouse ',
    countedBy: ' Sam ',
    items: [{ sku: 'SKU-1', quantity: 12 }],
  });

  const log = sheets['Inventory Log'];
  assert.deepEqual(JSON.parse(JSON.stringify(log.appended[0])), ['Timestamp', 'Warehouse', 'Counted By', 'SKU', 'Product Name', 'Price', 'Quantity']);
  assert.equal(log.frozenRows, 1);
  assert.equal(log.writes.length, 1);
  assert.deepEqual(JSON.parse(JSON.stringify(log.writes[0].data[0].slice(1))), ['North Warehouse', 'Sam', 'SKU-1', 'Cleaner', '$129', 12]);
  assert.ok(log.writes[0].data[0][0] instanceof Date);
  assert.deepEqual(lockEvents, [['wait', 30000], ['release']]);
  assert.equal(result.saved, 1);
});
