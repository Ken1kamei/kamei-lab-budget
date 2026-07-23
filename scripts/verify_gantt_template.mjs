import fs from "node:fs/promises";
import path from "node:path";

import { FileBlob, SpreadsheetFile } from "@oai/artifact-tool";

const repoRoot = path.resolve(import.meta.dirname, "..");
const outputPath = path.join(
  repoRoot,
  "outputs",
  "project-gantt-dynamic-20260723",
  "Kamei_Lab_Gantt_Import_Template.xlsx",
);
const templatePath = path.join(
  repoRoot,
  "web_app",
  "labapps",
  "static",
  "labapps",
  "Kamei_Lab_Gantt_Import_Template.xlsx",
);
const previewPath =
  "/private/tmp/kamei-gantt-artifact/dynamic-input-check.png";
const formulaErrorPattern =
  "#REF!|#DIV/0!|#VALUE!|#NAME\\?|#N/A|#NUM!|#NULL!|#SPILL!|#CALC!";
const firstTimelineColumn = 9;
const timelineDays = 371;

function columnLabel(columnNumber) {
  let value = columnNumber;
  let label = "";
  while (value > 0) {
    value -= 1;
    label = String.fromCharCode(65 + (value % 26)) + label;
    value = Math.floor(value / 26);
  }
  return label;
}

function excelSerial(isoDate) {
  const excelEpoch = Date.parse("1899-12-30T00:00:00Z");
  const date = Date.parse(`${isoDate}T00:00:00Z`);
  return Math.round((date - excelEpoch) / 86_400_000);
}

const outputBytes = await fs.readFile(outputPath);
const staticBytes = await fs.readFile(templatePath);
if (!outputBytes.equals(staticBytes)) {
  throw new Error("Output and distributed static template do not match.");
}

const blob = await FileBlob.load(templatePath);
const workbook = await SpreadsheetFile.importXlsx(blob);
const sheet = workbook.worksheets.getItem("Gantt Import");

sheet.getRange("A8:H8").values = [[
  "Planning",
  "Dynamic date verification",
  "kk4801@nyu.edu",
  "2026-09-03",
  "2027-08-31",
  50,
  "In progress",
  "Review generated timeline",
]];

const summaryCheck = await workbook.inspect({
  kind: "table",
  sheetId: "Gantt Import",
  range: "A1:V9",
  maxChars: 12000,
  tableMaxRows: 9,
  tableMaxCols: 22,
});
const summaryTable = JSON.parse(summaryCheck.ndjson);
const values = summaryTable.values;
const projectStart = excelSerial("2026-09-03");
const projectEnd = excelSerial("2027-08-31");
const calendarStart = excelSerial("2026-08-31");
const endOffset = projectEnd - calendarStart;
const endColumn = firstTimelineColumn + endOffset;
const nextColumn = endColumn + 1;
const endColumnLabel = columnLabel(endColumn);
const nextColumnLabel = columnLabel(nextColumn);
const lastTimelineLabel = columnLabel(
  firstTimelineColumn + timelineDays - 1,
);
const normalizedStartLabel = columnLabel(
  firstTimelineColumn + timelineDays,
);
const normalizedEndLabel = columnLabel(
  firstTimelineColumn + timelineDays + 1,
);
const endCheck = await workbook.inspect({
  kind: "table",
  sheetId: "Gantt Import",
  range: `${endColumnLabel}5:${nextColumnLabel}7`,
  maxChars: 4000,
  tableMaxRows: 3,
  tableMaxCols: 2,
});
const endValues = JSON.parse(endCheck.ndjson).values;
const tailFormulaCheck = await workbook.inspect({
  kind: "formula",
  sheetId: "Gantt Import",
  range: `${lastTimelineLabel}5:${normalizedEndLabel}9`,
  maxChars: 6000,
  options: { maxResults: 50 },
});
const actual = {
  projectStart: values[1][3],
  projectEnd: values[1][5],
  calendarStart: values[2][3],
  calendarEnd: values[2][5],
  firstWeekLabel: values[4][8],
  firstTimelineDate: values[5][8],
  firstWeekday: values[6][8],
  secondWeekLabel: values[4][15],
  secondWeekDate: values[5][15],
  endDate: endValues[1][0],
  endWeekday: endValues[2][0],
  nextDate: endValues[1][1] ?? "",
  nextWeekday: endValues[2][1] ?? "",
  task: values[7][1],
};
const expected = {
  projectStart,
  projectEnd,
  calendarStart,
  calendarEnd: projectEnd,
  firstWeekLabel: calendarStart,
  firstTimelineDate: calendarStart,
  firstWeekday: "M",
  secondWeekLabel: calendarStart + 7,
  secondWeekDate: calendarStart + 7,
  endDate: projectEnd,
  endWeekday: "T",
  nextDate: "",
  nextWeekday: "",
  task: "Dynamic date verification",
};

for (const [field, expectedValue] of Object.entries(expected)) {
  if (actual[field] !== expectedValue) {
    throw new Error(
      `${field} did not recalculate: expected ${expectedValue}, got ${actual[field]}`,
    );
  }
}

const errors = await workbook.inspect({
  kind: "match",
  searchTerm: formulaErrorPattern,
  options: { useRegex: true, maxResults: 100 },
  summary: "formula error scan",
});
const errorEntries = errors.ndjson
  .split("\n")
  .filter(Boolean)
  .map((line) => JSON.parse(line))
  .filter((entry) => entry.kind !== "notice");
if (errorEntries.length > 0) {
  throw new Error(`Formula error scan failed: ${JSON.stringify(errorEntries)}`);
}
if (!tailFormulaCheck.ndjson.includes(`${lastTimelineLabel}6`)) {
  throw new Error(
    `The final timeline formula is missing from ${lastTimelineLabel}6.`,
  );
}
if (!tailFormulaCheck.ndjson.includes(`${normalizedStartLabel}8`)) {
  throw new Error(
    `The normalized text-date formula is missing from ${normalizedStartLabel}8.`,
  );
}

const preview = await workbook.render({
  sheetName: "Gantt Import",
  range: "A1:CN14",
  scale: 1,
  format: "png",
});
await fs.mkdir(path.dirname(previewPath), { recursive: true });
await fs.writeFile(
  previewPath,
  new Uint8Array(await preview.arrayBuffer()),
);

console.log(
  JSON.stringify({
    ok: true,
    templatePath,
    previewPath,
    actual,
  }),
);
