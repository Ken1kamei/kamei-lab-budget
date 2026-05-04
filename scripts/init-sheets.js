// One-time spreadsheet initialization script.
// Uses clasp's stored OAuth credentials to call the Sheets API directly.

const { google } = require('googleapis');
const fs = require('fs');
const path = require('path');

const SPREADSHEET_ID = '1Ga6kOPohYxqQbt9ZoNXUma9Tf3cNmlxCJdvxp5edVWE';
const NYUAD_PURPLE = { red: 0.341, green: 0.024, blue: 0.549 };
const WHITE = { red: 1, green: 1, blue: 1 };
const CATEGORIES = ['Equipment', 'Personnel', 'Travel', 'Other'];

async function getAuthClient() {
  const clasprc = JSON.parse(fs.readFileSync(path.join(process.env.HOME, '.clasprc.json')));
  const tokens = clasprc.tokens.default;
  const client = new google.auth.OAuth2(
    tokens.client_id || '1072944905499-vm2v2i5dvn0a0d2o.apps.googleusercontent.com',
    tokens.client_secret,
    tokens.redirect_uris ? tokens.redirect_uris[0] : 'http://localhost'
  );
  client.setCredentials({
    access_token:  tokens.access_token,
    refresh_token: tokens.refresh_token,
    token_type:    tokens.token_type,
    expiry_date:   tokens.expiry_date
  });
  return client;
}

function headerFormat(sheetId) {
  return {
    repeatCell: {
      range: { sheetId, startRowIndex: 0, endRowIndex: 1 },
      cell: {
        userEnteredFormat: {
          backgroundColor: NYUAD_PURPLE,
          textFormat: { foregroundColor: WHITE, bold: true },
          verticalAlignment: 'MIDDLE'
        }
      },
      fields: 'userEnteredFormat(backgroundColor,textFormat,verticalAlignment)'
    }
  };
}

function freezeRow(sheetId) {
  return {
    updateSheetProperties: {
      properties: { sheetId, gridProperties: { frozenRowCount: 1 } },
      fields: 'gridProperties.frozenRowCount'
    }
  };
}

function setValues(sheetId, rows) {
  return {
    updateCells: {
      range: { sheetId, startRowIndex: 0, startColumnIndex: 0 },
      rows: rows.map(row => ({
        values: row.map(v => ({ userEnteredValue: { stringValue: String(v) } }))
      })),
      fields: 'userEnteredValue'
    }
  };
}

function dropdown(sheetId, startRow, colIndex, options) {
  return {
    setDataValidation: {
      range: { sheetId, startRowIndex: startRow, endRowIndex: 1000, startColumnIndex: colIndex, endColumnIndex: colIndex + 1 },
      rule: {
        condition: { type: 'ONE_OF_LIST', values: options.map(v => ({ userEnteredValue: v })) },
        showCustomUi: true, strict: true
      }
    }
  };
}

async function run() {
  const auth = await getAuthClient();
  const sheets = google.sheets({ version: 'v4', auth });

  // --- 1. Get existing sheets ---
  const meta = await sheets.spreadsheets.get({ spreadsheetId: SPREADSHEET_ID });
  const existing = meta.data.sheets.map(s => s.properties.title);
  console.log('Existing sheets:', existing);

  const needed = ['Summary', 'Transactions', 'Equipment', 'Personnel', 'Travel', 'Receipts', 'Other', 'Config'];
  const toAdd = needed.filter(n => !existing.includes(n));
  const toRename = existing[0] !== needed[0] ? [{ from: existing[0], to: needed[0] }] : [];

  const requests = [];

  // Rename default "Sheet1" to "Summary" if needed
  if (existing.includes('Sheet1') && !existing.includes('Summary')) {
    const sheetId = meta.data.sheets.find(s => s.properties.title === 'Sheet1').properties.sheetId;
    requests.push({ updateSheetProperties: { properties: { sheetId, title: 'Summary' }, fields: 'title' } });
  }

  // Add missing sheets
  for (const name of toAdd.filter(n => n !== 'Summary')) {
    requests.push({ addSheet: { properties: { title: name } } });
  }

  if (requests.length > 0) {
    await sheets.spreadsheets.batchUpdate({ spreadsheetId: SPREADSHEET_ID, requestBody: { requests } });
    console.log('Created sheets:', toAdd);
  }

  // Refresh sheet metadata
  const meta2 = await sheets.spreadsheets.get({ spreadsheetId: SPREADSHEET_ID });
  const sheetMap = {};
  meta2.data.sheets.forEach(s => { sheetMap[s.properties.title] = s.properties.sheetId; });
  console.log('Sheet IDs:', sheetMap);

  // --- 2. Set up each sheet ---
  const batchRequests = [];

  // SUMMARY
  const sumId = sheetMap['Summary'];
  const sumHeaders = ['Category','Budgeted (AED)','Budgeted (USD)','Budgeted (AED equiv)','Spent (AED)','Spent (USD)','Spent (AED equiv)','Remaining (AED equiv)','% Used','Visual'];
  const sumRows = [sumHeaders, ...CATEGORIES.map(c => [c,0,0,0,0,0,0,0,0,'']), ['TOTAL',0,0,0,0,0,0,0,0,'']];
  batchRequests.push(setValues(sumId, sumRows), headerFormat(sumId), freezeRow(sumId));

  // TRANSACTIONS
  const txnId = sheetMap['Transactions'];
  const txnHeaders = ['Transaction ID','Date','Fiscal Year','Category','Sub-category','Vendor / Payee','Description','PO Number','Invoice Number','Amount (AED)','Amount (USD)','Amount (AED equiv)','Status','Receipt Confirmed','PDF Link','Email Thread ID','Entered By','Entry Method','Notes','Last Modified'];
  batchRequests.push(setValues(txnId, [txnHeaders]), headerFormat(txnId), freezeRow(txnId));
  batchRequests.push(dropdown(txnId, 1, 3, CATEGORIES));  // Category col D
  batchRequests.push(dropdown(txnId, 1, 12, ['Pending Review','Ordered','Delivered','Paid','Cancelled']));  // Status col M
  // Checkbox for Receipt Confirmed (col N = index 13)
  batchRequests.push({
    repeatCell: {
      range: { sheetId: txnId, startRowIndex: 1, endRowIndex: 1000, startColumnIndex: 13, endColumnIndex: 14 },
      cell: { dataValidation: { condition: { type: 'BOOLEAN' } } },
      fields: 'dataValidation'
    }
  });

  // EQUIPMENT
  const eqId = sheetMap['Equipment'];
  const eqHeaders = [...txnHeaders, 'Delivery Date','Delivery Confirmed By','Asset Tag','Grant Code'];
  batchRequests.push(setValues(eqId, [eqHeaders]), headerFormat(eqId), freezeRow(eqId));

  // PERSONNEL
  const persnId = sheetMap['Personnel'];
  const persnHeaders = [...txnHeaders, 'Employee Name','Position','Employment Type','Pay Period Start','Pay Period End','Grant Code'];
  batchRequests.push(setValues(persnId, [persnHeaders]), headerFormat(persnId), freezeRow(persnId));

  // TRAVEL
  const trvId = sheetMap['Travel'];
  const trvHeaders = [...txnHeaders, 'Traveler Name','Destination','Purpose','Conference Name','Departure Date','Return Date','Grant Code'];
  batchRequests.push(setValues(trvId, [trvHeaders]), headerFormat(trvId), freezeRow(trvId));

  // RECEIPTS
  const rcpId = sheetMap['Receipts'];
  const rcpHeaders = ['Receipt ID','Linked Transaction ID','Receipt Date','Received By','Condition','PDF Link','Notes'];
  batchRequests.push(setValues(rcpId, [rcpHeaders]), headerFormat(rcpId), freezeRow(rcpId));
  batchRequests.push(dropdown(rcpId, 1, 4, ['OK','Damaged','Partial','Missing']));

  // OTHER
  const othId = sheetMap['Other'];
  batchRequests.push(setValues(othId, [txnHeaders]), headerFormat(othId), freezeRow(othId));

  // CONFIG
  const cfgId = sheetMap['Config'];
  const cfgRows = [
    ['Key', 'Value'],
    ['Fiscal Year', 'FY2025-26'],
    ['AED/USD Exchange Rate', '3.6725'],
    ['Rate Last Updated', new Date().toISOString().split('T')[0]],
    ['Registered Users', ''],
    ['Pending Registrations', ''],
    ['Notification Threshold %', '80'],
    ['Drive Folder ID (Invoices)', ''],
    ['Gmail Label', 'Budget/Invoices'],
  ];
  batchRequests.push(setValues(cfgId, cfgRows), headerFormat(cfgId), freezeRow(cfgId));

  // Execute all formatting
  await sheets.spreadsheets.batchUpdate({
    spreadsheetId: SPREADSHEET_ID,
    requestBody: { requests: batchRequests }
  });
  console.log('✓ All sheets initialized with headers and formatting.');

  // --- 3. Add SPARKLINE formulas to Summary (rows 2-5) via values API ---
  for (let i = 0; i < CATEGORIES.length; i++) {
    const row = i + 2; // 1-indexed, row 1 is header
    await sheets.spreadsheets.values.update({
      spreadsheetId: SPREADSHEET_ID,
      range: `Summary!J${row}`,
      valueInputOption: 'USER_ENTERED',
      requestBody: { values: [[`=IFERROR(SPARKLINE(I${row},{"charttype","bar";"max",1;"color1",IF(I${row}>0.9,"#cc0000",IF(I${row}>0.7,"#ff9900","#34a853"))}),"")` ]] }
    });
  }
  console.log('✓ Sparkline formulas added to Summary.');

  console.log('\n✅ Spreadsheet initialization complete!');
  console.log(`   Open: https://docs.google.com/spreadsheets/d/${SPREADSHEET_ID}/edit`);
}

run().catch(err => {
  console.error('Error:', err.message || err);
  process.exit(1);
});
