import fs from "node:fs/promises";
import path from "node:path";

import { SpreadsheetFile, Workbook } from "@oai/artifact-tool";

const repoRoot = path.resolve(import.meta.dirname, "..");
const outputDir = path.join(repoRoot, "outputs", "project-gantt-20260723");
const outputPath = path.join(
  outputDir,
  "Kamei_Lab_Gantt_Import_Template.xlsx",
);
const staticPath = path.join(
  repoRoot,
  "web_app",
  "labapps",
  "static",
  "labapps",
  "Kamei_Lab_Gantt_Import_Template.xlsx",
);
const previewDir = "/private/tmp/kamei-gantt-artifact/template-previews";

const colors = {
  navy: "#17213A",
  navyLight: "#E9EEF8",
  cyan: "#16B8A6",
  cyanLight: "#DDF6F2",
  magenta: "#D83BA8",
  amber: "#F3C43B",
  ink: "#172033",
  muted: "#5D6880",
  white: "#FFFFFF",
  grid: "#CFD7E6",
};

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

function styleScheduleSheet(sheet, { exampleRows = [] } = {}) {
  const firstTimelineColumn = 9;
  const timelineDays = 84;
  const lastTimelineColumn = firstTimelineColumn + timelineDays - 1;
  const lastTimelineLabel = columnLabel(lastTimelineColumn);
  const firstDataRow = 6;
  const lastDataRow = 35;

  sheet.showGridLines = false;
  sheet.mergeCells("A1:H1");
  sheet.getRange("A1").values = [["Kamei Lab Project Gantt"]];
  sheet.getRange("A1:H1").format = {
    fill: colors.navy,
    font: { bold: true, color: colors.white, size: 22 },
    verticalAlignment: "center",
  };
  sheet.getRange("A1:H1").format.rowHeight = 38;

  sheet.getRange("A2:H3").values = [
    ["Project name", "", "Project start", new Date("2026-09-01"), "", "", "Tasks", null],
    [
      "Use one row per task. Enter lab roster name, NYU email, or member ID in Assigned to.",
      null,
      null,
      null,
      null,
      null,
      "Average progress",
      null,
    ],
  ];
  sheet.getRange("A2:H3").format = {
    fill: colors.navyLight,
    font: { color: colors.ink },
    wrapText: true,
    verticalAlignment: "center",
  };
  sheet.getRange("A2").format.font = { bold: true, color: colors.ink };
  sheet.getRange("C2").format.font = { bold: true, color: colors.ink };
  sheet.getRange("G2:G3").format.font = { bold: true, color: colors.ink };
  sheet.getRange("D2").setNumberFormat("yyyy-mm-dd");
  sheet.getRange("H2").formulas = [[`=COUNTIF(B${firstDataRow}:B${lastDataRow},"<>")`]];
  sheet.getRange("H3").formulas = [[`=IFERROR(AVERAGE(F${firstDataRow}:F${lastDataRow}),0)`]];
  sheet.getRange("H3").setNumberFormat('0"%"');

  const headers = [
    "Phase",
    "Task",
    "Assigned to",
    "Start Date",
    "End Date",
    "Progress %",
    "Status",
    "Next Action",
  ];
  sheet.getRange("A5:H5").values = [headers];
  sheet.getRange("A5:H5").format = {
    fill: colors.navy,
    font: { bold: true, color: colors.white },
    horizontalAlignment: "center",
    verticalAlignment: "center",
    wrapText: true,
    borders: { preset: "all", style: "thin", color: colors.grid },
  };

  const timelineFormulas = Array.from({ length: timelineDays }, (_, index) =>
    index === 0 ? "=$D$2" : `=${columnLabel(firstTimelineColumn + index - 1)}5+1`,
  );
  sheet.getRange(`I5:${lastTimelineLabel}5`).formulas = [timelineFormulas];
  sheet.getRange(`I5:${lastTimelineLabel}5`).setNumberFormat("d");
  sheet.getRange(`I5:${lastTimelineLabel}5`).format = {
    fill: colors.navy,
    font: { bold: true, color: colors.white, size: 9 },
    horizontalAlignment: "center",
    borders: { preset: "all", style: "thin", color: colors.grid },
  };

  const blankRows = Array.from({ length: lastDataRow - firstDataRow + 1 }, () =>
    Array(8).fill(null),
  );
  for (let index = 0; index < exampleRows.length; index += 1) {
    blankRows[index] = exampleRows[index];
  }
  sheet.getRange(`A${firstDataRow}:H${lastDataRow}`).values = blankRows;
  sheet.getRange(`A${firstDataRow}:H${lastDataRow}`).format = {
    font: { color: colors.ink },
    borders: { preset: "all", style: "thin", color: colors.grid },
    verticalAlignment: "center",
    wrapText: true,
  };
  sheet.getRange(`D${firstDataRow}:E${lastDataRow}`).setNumberFormat("yyyy-mm-dd");
  sheet.getRange(`F${firstDataRow}:F${lastDataRow}`).setNumberFormat('0"%"');
  sheet.getRange(`F${firstDataRow}:F${lastDataRow}`).dataValidation = {
    rule: { type: "whole", operator: "between", formula1: 0, formula2: 100 },
  };
  sheet.getRange(`G${firstDataRow}:G${lastDataRow}`).dataValidation = {
    rule: {
      type: "list",
      values: ["Not started", "In progress", "Blocked", "Completed"],
    },
  };

  sheet.getRange(`I${firstDataRow}:${lastTimelineLabel}${lastDataRow}`).format = {
    fill: colors.white,
    borders: { preset: "all", style: "thin", color: "#E6EAF1" },
  };
  sheet
    .getRange(`I${firstDataRow}:${lastTimelineLabel}${lastDataRow}`)
    .conditionalFormats.addCustom(
      `=AND(I$5>=$D${firstDataRow},I$5<=$E${firstDataRow},$B${firstDataRow}<>"")`,
      { fill: colors.cyanLight },
    );
  sheet
    .getRange(`I${firstDataRow}:${lastTimelineLabel}${lastDataRow}`)
    .conditionalFormats.addCustom(
      `=AND(I$5>=$D${firstDataRow},I$5<=$D${firstDataRow}+ROUND(($E${firstDataRow}-$D${firstDataRow}+1)*$F${firstDataRow}/100,0)-1,$B${firstDataRow}<>"")`,
      { fill: colors.cyan },
    );

  sheet.getRange("A:A").format.columnWidth = 18;
  sheet.getRange("B:B").format.columnWidth = 31;
  sheet.getRange("C:C").format.columnWidth = 24;
  sheet.getRange("D:E").format.columnWidth = 13;
  sheet.getRange("F:F").format.columnWidth = 12;
  sheet.getRange("G:G").format.columnWidth = 15;
  sheet.getRange("H:H").format.columnWidth = 28;
  sheet.getRange(`I:${lastTimelineLabel}`).format.columnWidth = 4.2;
  sheet.getRange(`${firstDataRow}:${lastDataRow}`).format.rowHeight = 27;
  sheet.freezePanes.freezeRows(5);
  sheet.freezePanes.freezeColumns(8);
  sheet.tables.add(`A5:H${lastDataRow}`, true, `${sheet.name.replaceAll(" ", "")}Tasks`);
}

const workbook = Workbook.create();
const ganttSheet = workbook.worksheets.add("Gantt Import");
styleScheduleSheet(ganttSheet);

const exampleSheet = workbook.worksheets.add("Example");
styleScheduleSheet(exampleSheet, {
  exampleRows: [
    ["Planning", "Define research question", "kk4801@nyu.edu", new Date("2026-09-01"), new Date("2026-09-05"), 100, "Completed", "Confirm study scope"],
    ["Planning", "Confirm assay readouts", "Team lead", new Date("2026-09-04"), new Date("2026-09-12"), 70, "In progress", "Review pilot data"],
    ["Experimental setup", "Order critical materials", "Lab member", new Date("2026-09-06"), new Date("2026-09-18"), 40, "In progress", "Confirm delivery dates"],
    ["Experimental setup", "Run pilot experiment", "Lab member", new Date("2026-09-19"), new Date("2026-10-02"), 0, "Not started", "Finalize protocol"],
    ["Analysis", "Quality control and analysis", "Team lead", new Date("2026-10-03"), new Date("2026-10-16"), 0, "Not started", "Prepare analysis plan"],
    ["Reporting", "Team review and figure preparation", "kk4801@nyu.edu", new Date("2026-10-17"), new Date("2026-10-30"), 0, "Not started", "Schedule lab review"],
  ],
});
exampleSheet.getRange("B2").values = [["Example reverse-bioengineering study"]];

const instructions = workbook.worksheets.add("Instructions");
instructions.showGridLines = false;
instructions.mergeCells("A1:F1");
instructions.getRange("A1").values = [["Kamei Lab Gantt Import Instructions"]];
instructions.getRange("A1:F1").format = {
  fill: colors.navy,
  font: { bold: true, color: colors.white, size: 20 },
};
instructions.getRange("A3:F12").values = [
  ["Step", "What to do", "Required", "Accepted values", "Web app behavior", "Notes"],
  ["1", "Open the Gantt Import sheet.", "Yes", "", "The app reads this sheet first.", "Do not rename the Task, Start Date, or End Date headers."],
  ["2", "Enter one task per row.", "Yes", "Plain text", "Each row becomes a Project Tracker milestone.", "Phase may repeat across rows."],
  ["3", "Enter Assigned to.", "Recommended", "Member ID, NYU email, full name, or display name", "Unmatched names use the default owner selected during upload.", "Keep the lab roster spelling."],
  ["4", "Enter Start Date and End Date.", "Yes", "Excel date", "Tasks with missing or reversed dates are blocked before import.", "Use yyyy-mm-dd when typing."],
  ["5", "Enter Progress %.", "No", "0 to 100", "Status is inferred when Status is blank.", "100 becomes Completed."],
  ["6", "Choose Status.", "No", "Not started, In progress, Blocked, Completed", "The selected status is saved to Google Sheets.", ""],
  ["7", "Upload in Project Tracker > Gantt chart.", "Yes", ".xlsx up to 10 MB", "The app shows a preview before any write.", ""],
  ["8", "Confirm the preview.", "Yes", "", "Only prior Excel-imported Gantt tasks for that project are replaced.", "Manual milestones and other projects remain unchanged."],
  ["Tip", "Use the Example sheet as a visual reference.", "", "", "", "Copy only your own rows into Gantt Import."],
];
instructions.getRange("A3:F3").format = {
  fill: colors.navy,
  font: { bold: true, color: colors.white },
};
instructions.getRange("A4:F12").format = {
  borders: { preset: "all", style: "thin", color: colors.grid },
  wrapText: true,
  verticalAlignment: "top",
};
instructions.getRange("A:A").format.columnWidth = 10;
instructions.getRange("B:B").format.columnWidth = 34;
instructions.getRange("C:C").format.columnWidth = 14;
instructions.getRange("D:D").format.columnWidth = 38;
instructions.getRange("E:E").format.columnWidth = 38;
instructions.getRange("F:F").format.columnWidth = 34;
instructions.getRange("4:12").format.rowHeight = 48;
instructions.freezePanes.freezeRows(3);

const reference = workbook.worksheets.add("Reference");
reference.showGridLines = false;
reference.getRange("A1:D1").values = [["Field", "Required", "Purpose", "Example"]];
reference.getRange("A1:D1").format = {
  fill: colors.navy,
  font: { bold: true, color: colors.white },
};
reference.getRange("A2:D9").values = [
  ["Phase", "No", "Groups related tasks", "Experimental setup"],
  ["Task", "Yes", "Milestone or activity name", "Run pilot experiment"],
  ["Assigned to", "Recommended", "Lab roster match", "kk4801@nyu.edu"],
  ["Start Date", "Yes", "Task start", new Date("2026-09-01")],
  ["End Date", "Yes", "Task deadline", new Date("2026-09-14")],
  ["Progress %", "No", "Completion from 0 to 100", 50],
  ["Status", "No", "Current task state", "In progress"],
  ["Next Action", "No", "Immediate follow-up", "Review pilot data"],
];
reference.getRange("A2:D9").format = {
  borders: { preset: "all", style: "thin", color: colors.grid },
  wrapText: true,
};
reference.getRange("D5:D6").setNumberFormat("yyyy-mm-dd");
reference.getRange("A:D").format.columnWidth = 28;

await fs.mkdir(outputDir, { recursive: true });
await fs.mkdir(path.dirname(staticPath), { recursive: true });
await fs.mkdir(previewDir, { recursive: true });

for (const [sheetName, range] of [
  ["Gantt Import", "A1:U18"],
  ["Example", "A1:U18"],
  ["Instructions", "A1:F12"],
  ["Reference", "A1:D9"],
]) {
  const preview = await workbook.render({ sheetName, range, scale: 1, format: "png" });
  const previewPath = path.join(
    previewDir,
    `${sheetName.toLowerCase().replaceAll(" ", "-")}.png`,
  );
  await fs.writeFile(previewPath, new Uint8Array(await preview.arrayBuffer()));
}

const check = await workbook.inspect({
  kind: "table",
  sheetId: "Example",
  range: "A1:H12",
  maxChars: 12000,
  tableMaxRows: 12,
  tableMaxCols: 8,
});
const errors = await workbook.inspect({
  kind: "match",
  searchTerm: "#REF!|#DIV/0!|#VALUE!|#NAME\\?|#N/A",
  options: { useRegex: true, maxResults: 100 },
  summary: "formula error scan",
});
console.log(JSON.stringify({ check, errors }, null, 2));

const output = await SpreadsheetFile.exportXlsx(workbook);
await output.save(outputPath);
await fs.copyFile(outputPath, staticPath);
console.log(JSON.stringify({ outputPath, staticPath, previewDir }));
