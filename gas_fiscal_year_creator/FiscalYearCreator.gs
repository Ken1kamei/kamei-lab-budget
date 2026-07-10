/**
 * Creates and removes annual Kamei Lab Budget workbooks in the PI's My Drive.
 *
 * Streamlit queues a request in the master workbook's Config sheet. This
 * installable trigger runs as the PI, so no external Web App or static secret
 * is needed and Drive ownership remains with the PI.
 */

const DEFAULT_MASTER_SPREADSHEET_ID = '1Ga6kOPohYxqQbt9ZoNXUma9Tf3cNmlxCJdvxp5edVWE';
const DEFAULT_SERVICE_ACCOUNT_EMAIL = 'budget-app@kamei-lab-budget.iam.gserviceaccount.com';
const TEMPLATE_CONFIG_KEY = 'Fiscal Year Template Spreadsheet ID';
const FY_SPREADSHEET_CONFIG_PREFIX = 'Spreadsheet ID ';
const FY_CREATION_REQUEST_PREFIX = 'Fiscal Year Creation Request ';
const FY_DELETION_REQUEST_PREFIX = 'Fiscal Year Deletion Request ';
const CREATOR_TRIGGER_STATUS_KEY = 'Fiscal Year Creator Trigger Status';
const CREATOR_TRIGGER_HEARTBEAT_KEY = 'Fiscal Year Creator Trigger Heartbeat';
const CREATOR_MANAGED_KEY = 'Fiscal Year Creator Managed';
const CREATOR_FISCAL_YEAR_KEY = 'Fiscal Year Creator Fiscal Year';
const TEMPLATE_TITLE = 'KameiLab Budget Template';
const FISCAL_YEAR_SHEET_NAMES = ['Transactions', 'Summary', 'Teams', 'Config'];
const TRANSACTION_HEADERS = [
  'Transaction ID', 'Date', 'Fiscal Year', 'Category', 'Sub-category',
  'Vendor / Payee', 'Description', 'PO Number', 'Invoice Number',
  'Currency', 'Amount', 'Amount (USD equiv)',
  'Amount (AED)', 'Amount (USD)', 'Amount (AED equiv)', 'Status',
  'Receipt Confirmed', 'PDF Link', 'Email Thread ID', 'Entered By',
  'Entry Method', 'Notes', 'Last Modified', 'Team', 'Approved By', 'Approved At',
];
const SUMMARY_HEADERS = [
  'Category',
  'Budgeted (AED)', 'Budgeted (USD)', 'Budgeted (AED equiv)',
  'Spent (AED)', 'Spent (USD)', 'Spent (AED equiv)',
  'Remaining (AED equiv)', '% Used', 'Visual',
];
const TEAM_HEADERS = [
  'Team Name', 'Allocation (AED)', 'Allocation (USD)',
  'Budget Manager Emails', 'Budget Manager Names',
  'Lead Emails', 'Lead Names', 'Member Emails', 'Member Names',
  'Description', 'Active',
];
const CATEGORIES = ['Equipment', 'Consumables', 'Personnel', 'Travel', 'Publications', 'Memberships', 'Other'];

/** Run once as the PI to install the one-minute processing trigger. */
function setupFiscalYearCreatorTrigger() {
  ScriptApp.getProjectTriggers().forEach(function (trigger) {
    if (trigger.getHandlerFunction() === 'processFiscalYearCreationQueue') {
      ScriptApp.deleteTrigger(trigger);
    }
  });
  ScriptApp.newTrigger('processFiscalYearCreationQueue').timeBased().everyMinutes(1).create();
  const master = SpreadsheetApp.openById(getCreatorConfig_().masterSpreadsheetId);
  setConfigValue_(master.getSheetByName('Config'), CREATOR_TRIGGER_STATUS_KEY, 'Enabled ' + new Date().toISOString());
  processFiscalYearCreationQueue();
}

/** Runs as the PI every minute and processes queued Streamlit requests. */
function processFiscalYearCreationQueue() {
  const lock = LockService.getScriptLock();
  if (!lock.tryLock(1000)) {
    return;
  }
  try {
    const config = getCreatorConfig_();
    const master = SpreadsheetApp.openById(config.masterSpreadsheetId);
    const configSheet = requireSheet_(master, 'Config');
    const rows = configSheet.getDataRange().getValues();
    for (let index = 1; index < rows.length; index += 1) {
      const key = String(rows[index][0] || '').trim();
      const value = String(rows[index][1] || '').trim();
      const creationMatch = key.match(/^Fiscal Year Creation Request (FY\d{4}-\d{2})$/);
      const deletionMatch = key.match(/^Fiscal Year Deletion Request (FY\d{4}-\d{2})$/);
      if (creationMatch && /^(Queued|Migrate)/.test(value)) {
        processCreationRequest_(master, configSheet, creationMatch[1], value);
      } else if (deletionMatch && /^Queued/.test(value)) {
        processDeletionRequest_(configSheet, deletionMatch[1]);
      }
    }
    setConfigValue_(configSheet, CREATOR_TRIGGER_HEARTBEAT_KEY, 'Success ' + new Date().toISOString());
  } catch (error) {
    console.error(error && error.stack ? error.stack : error);
    throw error;
  } finally {
    lock.releaseLock();
  }
}

function getCreatorConfig_() {
  const properties = PropertiesService.getScriptProperties();
  return {
    masterSpreadsheetId: properties.getProperty('MASTER_SPREADSHEET_ID') || DEFAULT_MASTER_SPREADSHEET_ID,
    serviceAccountEmail: properties.getProperty('BUDGET_SERVICE_ACCOUNT_EMAIL') || DEFAULT_SERVICE_ACCOUNT_EMAIL,
  };
}

function processCreationRequest_(master, masterConfigSheet, fiscalYear, requestValue) {
  let workbook = null;
  let registered = false;
  try {
    const config = getCreatorConfig_();
    const workbookConfigKey = FY_SPREADSHEET_CONFIG_PREFIX + fiscalYear;
    const existingWorkbookId = getConfigValue_(masterConfigSheet, workbookConfigKey);
    const masterFiscalYear = getConfigValue_(masterConfigSheet, 'Current Fiscal Year') || getConfigValue_(masterConfigSheet, 'Fiscal Year');
    if (fiscalYear === masterFiscalYear) {
      throw new Error('The master ledger year cannot be recreated.');
    }
    if (existingWorkbookId && existingWorkbookId !== config.masterSpreadsheetId) {
      if (!isManagedFiscalYearWorkbook_(existingWorkbookId, fiscalYear)) {
        throw new Error('The registered workbook does not match this managed fiscal year.');
      }
      ensureBudgetServiceAccountEditor_(DriveApp.getFileById(existingWorkbookId));
      setConfigValue_(masterConfigSheet, FY_CREATION_REQUEST_PREFIX + fiscalYear, 'Complete ' + existingWorkbookId);
      return;
    }

    if (/^Migrate/.test(requestValue)) {
      if (existingWorkbookId !== config.masterSpreadsheetId) {
        throw new Error('This fiscal year is not stored in the legacy master workbook.');
      }
      workbook = copyLegacyFiscalYear_(master, fiscalYear);
    } else {
      const template = ensureTemplate_(master, masterConfigSheet);
      workbook = DriveApp.getFileById(template.getId()).makeCopy('KameiLab Budget ' + fiscalYear);
      shareWithBudgetServiceAccount_(workbook);
      initializeNewFiscalYearWorkbook_(SpreadsheetApp.openById(workbook.getId()), masterConfigSheet, fiscalYear);
    }

    setConfigValue_(masterConfigSheet, workbookConfigKey, workbook.getId());
    setConfigValue_(masterConfigSheet, FY_CREATION_REQUEST_PREFIX + fiscalYear, 'Complete ' + workbook.getId());
    registered = true;
  } catch (error) {
    if (workbook && !registered) {
      safeTrash_(workbook);
    }
    setConfigValue_(masterConfigSheet, FY_CREATION_REQUEST_PREFIX + fiscalYear, 'Error: ' + safeErrorMessage_(error));
  }
}

function processDeletionRequest_(masterConfigSheet, fiscalYear) {
  try {
    const config = getCreatorConfig_();
    const workbookConfigKey = FY_SPREADSHEET_CONFIG_PREFIX + fiscalYear;
    const workbookId = getConfigValue_(masterConfigSheet, workbookConfigKey);
    if (!workbookId || workbookId === config.masterSpreadsheetId) {
      throw new Error('No dedicated fiscal-year workbook is registered for deletion.');
    }
    if (!isManagedFiscalYearWorkbook_(workbookId, fiscalYear)) {
      throw new Error('The registered workbook is not a verified managed fiscal-year ledger.');
    }
    DriveApp.getFileById(workbookId).setTrashed(true);
    setConfigValue_(masterConfigSheet, workbookConfigKey, '');
    setConfigValue_(masterConfigSheet, FY_DELETION_REQUEST_PREFIX + fiscalYear, 'Complete ' + workbookId);
  } catch (error) {
    setConfigValue_(masterConfigSheet, FY_DELETION_REQUEST_PREFIX + fiscalYear, 'Error: ' + safeErrorMessage_(error));
  }
}

function ensureTemplate_(master, masterConfigSheet) {
  const existingTemplateId = getConfigValue_(masterConfigSheet, TEMPLATE_CONFIG_KEY);
  if (existingTemplateId && fileExists_(existingTemplateId)) {
    const template = DriveApp.getFileById(existingTemplateId);
    removeNonLedgerSheets_(SpreadsheetApp.openById(template.getId()));
    return template;
  }
  const config = getCreatorConfig_();
  const template = DriveApp.getFileById(config.masterSpreadsheetId).makeCopy(TEMPLATE_TITLE);
  shareWithBudgetServiceAccount_(template);
  const baseFiscalYear = getConfigValue_(masterConfigSheet, 'Current Fiscal Year') || getConfigValue_(masterConfigSheet, 'Fiscal Year');
  initializeNewFiscalYearWorkbook_(SpreadsheetApp.openById(template.getId()), masterConfigSheet, baseFiscalYear);
  setConfigValue_(masterConfigSheet, TEMPLATE_CONFIG_KEY, template.getId());
  return template;
}

function copyLegacyFiscalYear_(master, fiscalYear) {
  const template = ensureTemplate_(master, requireSheet_(master, 'Config'));
  const workbookFile = DriveApp.getFileById(template.getId()).makeCopy('KameiLab Budget ' + fiscalYear);
  shareWithBudgetServiceAccount_(workbookFile);
  const workbook = SpreadsheetApp.openById(workbookFile.getId());
  ['Transactions', 'Summary', 'Teams', 'Config'].forEach(function (name) {
    const legacy = master.getSheetByName(name + ' ' + fiscalYear);
    if (!legacy) {
      throw new Error('Missing legacy worksheet: ' + name + ' ' + fiscalYear);
    }
    const defaultSheet = workbook.getSheetByName(name);
    if (defaultSheet) {
      workbook.deleteSheet(defaultSheet);
    }
    legacy.copyTo(workbook).setName(name);
  });
  const configSheet = requireSheet_(workbook, 'Config');
  setConfigValue_(configSheet, CREATOR_MANAGED_KEY, 'true');
  setConfigValue_(configSheet, CREATOR_FISCAL_YEAR_KEY, fiscalYear);
  return workbookFile;
}

function initializeNewFiscalYearWorkbook_(workbook, masterConfigSheet, fiscalYear) {
  removeNonLedgerSheets_(workbook);
  const transactionSheet = getOrCreateSheet_(workbook, 'Transactions');
  transactionSheet.clearContents();
  transactionSheet.getRange(1, 1, 1, TRANSACTION_HEADERS.length).setValues([TRANSACTION_HEADERS]);

  const summarySheet = getOrCreateSheet_(workbook, 'Summary');
  summarySheet.clearContents();
  const summaryRows = CATEGORIES.map(function (category) {
    return [category, 0, 0, 0, 0, 0, 0, 0, 0, ''];
  });
  summaryRows.push(['TOTAL', 0, 0, 0, 0, 0, 0, 0, 0, '']);
  summarySheet.getRange(1, 1, 1, SUMMARY_HEADERS.length).setValues([SUMMARY_HEADERS]);
  summarySheet.getRange(2, 1, summaryRows.length, SUMMARY_HEADERS.length).setValues(summaryRows);

  const teamsSheet = getOrCreateSheet_(workbook, 'Teams');
  const previousTeamValues = teamsSheet.getDataRange().getValues();
  const teamRows = normaliseTeamRows_(previousTeamValues);
  teamsSheet.clearContents();
  teamsSheet.getRange(1, 1, 1, TEAM_HEADERS.length).setValues([TEAM_HEADERS]);
  if (teamRows.length) {
    teamsSheet.getRange(2, 1, teamRows.length, TEAM_HEADERS.length).setValues(teamRows);
  }

  const configSheet = getOrCreateSheet_(workbook, 'Config');
  const configRows = buildFiscalYearConfigRows_(masterConfigSheet, fiscalYear);
  configSheet.clearContents();
  configSheet.getRange(1, 1, 1, 2).setValues([['Key', 'Value']]);
  configSheet.getRange(2, 1, configRows.length, 2).setValues(configRows);
  setConfigValue_(configSheet, CREATOR_MANAGED_KEY, 'true');
  setConfigValue_(configSheet, CREATOR_FISCAL_YEAR_KEY, fiscalYear);
}

function removeNonLedgerSheets_(workbook) {
  workbook.getSheets().forEach(function (sheet) {
    if (FISCAL_YEAR_SHEET_NAMES.indexOf(sheet.getName()) === -1) {
      workbook.deleteSheet(sheet);
    }
  });
}

function normaliseTeamRows_(values) {
  if (!values.length) {
    return [];
  }
  const headerIndex = {};
  values[0].forEach(function (header, index) {
    headerIndex[String(header || '').trim()] = index;
  });
  return values.slice(1).filter(function (row) {
    return String(row[headerIndex['Team Name']] || '').trim();
  }).map(function (row) {
    return TEAM_HEADERS.map(function (header) {
      if (header === 'Allocation (AED)' || header === 'Allocation (USD)') {
        return 0;
      }
      const index = headerIndex[header];
      return index === undefined ? '' : row[index];
    });
  });
}

function buildFiscalYearConfigRows_(masterConfigSheet, fiscalYear) {
  const output = [];
  const seen = {};
  const values = masterConfigSheet.getDataRange().getValues();
  values.slice(1).forEach(function (row) {
    const key = String(row[0] || '').trim();
    if (!key || key.indexOf(FY_SPREADSHEET_CONFIG_PREFIX) === 0 ||
        key === TEMPLATE_CONFIG_KEY || key.indexOf(FY_CREATION_REQUEST_PREFIX) === 0 ||
        key.indexOf(FY_DELETION_REQUEST_PREFIX) === 0 || key === CREATOR_TRIGGER_STATUS_KEY ||
        key === CREATOR_TRIGGER_HEARTBEAT_KEY || key === CREATOR_MANAGED_KEY ||
        key === CREATOR_FISCAL_YEAR_KEY) {
      return;
    }
    let value = row[1] || '';
    if (key === 'Current Fiscal Year' || key === 'Fiscal Year') {
      value = fiscalYear;
    }
    output.push([key, value]);
    seen[key] = true;
  });
  [['Current Fiscal Year', fiscalYear], ['Fiscal Year', fiscalYear]].forEach(function (row) {
    if (!seen[row[0]]) {
      output.push(row);
    }
  });
  return output;
}

function getOrCreateSheet_(workbook, name) {
  const existing = workbook.getSheetByName(name);
  return existing || workbook.insertSheet(name);
}

function requireSheet_(workbook, name) {
  const sheet = workbook.getSheetByName(name);
  if (!sheet) {
    throw new Error('Missing required worksheet: ' + name);
  }
  return sheet;
}

function getConfigValue_(sheet, key) {
  const values = sheet.getDataRange().getValues();
  for (let index = 1; index < values.length; index += 1) {
    if (String(values[index][0] || '').trim() === key) {
      return String(values[index][1] || '').trim();
    }
  }
  return '';
}

function setConfigValue_(sheet, key, value) {
  const values = sheet.getDataRange().getValues();
  for (let index = 1; index < values.length; index += 1) {
    if (String(values[index][0] || '').trim() === key) {
      sheet.getRange(index + 1, 2).setValue(value);
      return;
    }
  }
  sheet.appendRow([key, value]);
}

function shareWithBudgetServiceAccount_(file) {
  ensureBudgetServiceAccountEditor_(file);
}

function ensureBudgetServiceAccountEditor_(file) {
  const serviceAccountEmail = getCreatorConfig_().serviceAccountEmail;
  const hasEditorAccess = file.getEditors().some(function (user) {
    return String(user.getEmail() || '').toLowerCase() === serviceAccountEmail.toLowerCase();
  });
  if (!hasEditorAccess) {
    file.addEditor(serviceAccountEmail);
  }
}

function isManagedFiscalYearWorkbook_(workbookId, fiscalYear) {
  try {
    const workbook = SpreadsheetApp.openById(workbookId);
    const hasStandardSheets = FISCAL_YEAR_SHEET_NAMES.every(function (name) {
      return Boolean(workbook.getSheetByName(name));
    });
    if (!hasStandardSheets) {
      return false;
    }
    const config = requireSheet_(workbook, 'Config');
    return getConfigValue_(config, CREATOR_MANAGED_KEY) === 'true' &&
      getConfigValue_(config, CREATOR_FISCAL_YEAR_KEY) === fiscalYear &&
      (getConfigValue_(config, 'Current Fiscal Year') === fiscalYear ||
        getConfigValue_(config, 'Fiscal Year') === fiscalYear);
  } catch (error) {
    return false;
  }
}

function safeTrash_(file) {
  try {
    file.setTrashed(true);
  } catch (error) {
    console.error('Could not trash partial fiscal-year workbook: ' + safeErrorMessage_(error));
  }
}

function fileExists_(fileId) {
  try {
    DriveApp.getFileById(fileId);
    return true;
  } catch (error) {
    return false;
  }
}

function safeErrorMessage_(error) {
  const message = error && error.message ? String(error.message) : 'Unexpected fiscal-year creator error.';
  return message.slice(0, 500);
}
