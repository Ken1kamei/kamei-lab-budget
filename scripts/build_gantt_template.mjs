import fs from "node:fs/promises";
import path from "node:path";

import { SpreadsheetFile, Workbook } from "@oai/artifact-tool";

const repoRoot = path.resolve(import.meta.dirname, "..");
const outputDir = path.join(
  repoRoot,
  "outputs",
  "project-gantt-dynamic-20260723",
);
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
const formulaErrorPattern =
  "#REF!|#DIV/0!|#VALUE!|#NAME\\?|#N/A|#NUM!|#NULL!|#SPILL!|#CALC!";

function formulaErrorMatches(result) {
  return result.ndjson
    .split("\n")
    .filter(Boolean)
    .map((line) => JSON.parse(line))
    .filter((entry) => entry.kind !== "notice");
}

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

const firstTimelineColumn = 9;
const timelineDays = 371;
const timelineWeeks = timelineDays / 7;
const lastTimelineColumn = firstTimelineColumn + timelineDays - 1;
const lastTimelineLabel = columnLabel(lastTimelineColumn);
const normalizedStartLabel = columnLabel(lastTimelineColumn + 1);
const normalizedEndLabel = columnLabel(lastTimelineColumn + 2);
const firstDataRow = 8;
const lastDataRow = 37;

function styleScheduleSheet(sheet, { exampleRows = [] } = {}) {
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
    [
      "Project name",
      "",
      "Project start (auto)",
      null,
      "Project end (auto)",
      null,
      "Tasks",
      null,
    ],
    [
      "Enter Start Date and End Date below. The calendar and Gantt bars update automatically.",
      "",
      "Calendar starts",
      null,
      "Calendar ends",
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
  sheet.getRange("C2:C3").format.font = { bold: true, color: colors.ink };
  sheet.getRange("E2:E3").format.font = { bold: true, color: colors.ink };
  sheet.getRange("G2:G3").format.font = { bold: true, color: colors.ink };
  sheet.getRange("D2").formulas = [
    [`=IF(COUNT(${normalizedStartLabel}${firstDataRow}:${normalizedStartLabel}${lastDataRow})=0,"",MIN(${normalizedStartLabel}${firstDataRow}:${normalizedStartLabel}${lastDataRow}))`],
  ];
  sheet.getRange("F2").formulas = [
    [`=IF(COUNT(${normalizedEndLabel}${firstDataRow}:${normalizedEndLabel}${lastDataRow})=0,"",MAX(${normalizedEndLabel}${firstDataRow}:${normalizedEndLabel}${lastDataRow}))`],
  ];
  sheet.getRange("D3").formulas = [
    ['=IF(D2="","",D2-WEEKDAY(D2,2)+1)'],
  ];
  sheet.getRange("F3").formulas = [
    ['=IF(F2="","",F2)'],
  ];
  sheet.getRange("D2:F3").setNumberFormat("yyyy-mm-dd");
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
  sheet.getRange("A7:H7").values = [headers];
  sheet.getRange("A7:H7").format = {
    fill: colors.navy,
    font: { bold: true, color: colors.white },
    horizontalAlignment: "center",
    verticalAlignment: "center",
    wrapText: true,
    borders: { preset: "all", style: "thin", color: colors.grid },
  };

  for (let weekIndex = 0; weekIndex < timelineWeeks; weekIndex += 1) {
    const firstWeekColumn = firstTimelineColumn + weekIndex * 7;
    const lastWeekColumn = firstWeekColumn + 6;
    const firstWeekLabel = columnLabel(firstWeekColumn);
    const lastWeekLabel = columnLabel(lastWeekColumn);
    sheet.mergeCells(`${firstWeekLabel}5:${lastWeekLabel}5`);
    sheet.getRange(`${firstWeekLabel}5`).formulas = [
      [`=IF(${firstWeekLabel}6="","",${firstWeekLabel}6)`],
    ];
  }
  sheet.getRange(`I5:${lastTimelineLabel}5`).setNumberFormat("mmm d, yyyy");
  sheet.getRange(`I5:${lastTimelineLabel}5`).format = {
    fill: colors.navy,
    font: { bold: true, color: colors.white, size: 9 },
    horizontalAlignment: "center",
    verticalAlignment: "center",
    borders: { preset: "all", style: "thin", color: colors.grid },
  };

  const timelineDateFormulas = Array.from({ length: timelineDays }, (_, index) =>
    index === 0
      ? '=IF($D$3="","",$D$3)'
      : `=IF(OR(${columnLabel(firstTimelineColumn + index - 1)}6="",${columnLabel(firstTimelineColumn + index - 1)}6>=$F$2),"",${columnLabel(firstTimelineColumn + index - 1)}6+1)`,
  );
  sheet.getRange(`I6:${lastTimelineLabel}6`).formulas = [timelineDateFormulas];
  sheet.getRange(`I6:${lastTimelineLabel}6`).setNumberFormat("d");
  sheet.getRange(`I6:${lastTimelineLabel}6`).format = {
    fill: colors.navy,
    font: { bold: true, color: colors.white, size: 9 },
    horizontalAlignment: "center",
    verticalAlignment: "center",
    borders: { preset: "all", style: "thin", color: colors.grid },
  };

  const timelineWeekdayFormulas = Array.from(
    { length: timelineDays },
    (_, index) => {
      const dateLabel = columnLabel(firstTimelineColumn + index);
      return `=IF(${dateLabel}6="","",CHOOSE(WEEKDAY(${dateLabel}6,2),"M","T","W","T","F","S","S"))`;
    },
  );
  sheet.getRange(`I7:${lastTimelineLabel}7`).formulas = [
    timelineWeekdayFormulas,
  ];
  sheet.getRange(`I7:${lastTimelineLabel}7`).format = {
    fill: colors.navy,
    font: { bold: true, color: colors.white, size: 9 },
    horizontalAlignment: "center",
    verticalAlignment: "center",
    borders: { preset: "all", style: "thin", color: colors.grid },
  };
  for (let weekIndex = 0; weekIndex < timelineWeeks; weekIndex += 1) {
    for (const dayOffset of [5, 6]) {
      const weekendLabel = columnLabel(
        firstTimelineColumn + weekIndex * 7 + dayOffset,
      );
      sheet.getRange(`${weekendLabel}6:${weekendLabel}7`).format.fill =
        "#31405A";
    }
  }

  const blankRows = Array.from({ length: lastDataRow - firstDataRow + 1 }, () =>
    Array(8).fill(null),
  );
  for (let index = 0; index < exampleRows.length; index += 1) {
    blankRows[index] = exampleRows[index];
  }
  sheet.getRange(`A${firstDataRow}:H${lastDataRow}`).values = blankRows;
  const normalizedDateFormulas = Array.from(
    { length: lastDataRow - firstDataRow + 1 },
    (_, index) => {
      const rowNumber = firstDataRow + index;
      return [
        `=IF(D${rowNumber}="","",IF(ISNUMBER(D${rowNumber}),D${rowNumber},IFERROR(DATE(LEFT(D${rowNumber},4),MID(D${rowNumber},6,2),RIGHT(D${rowNumber},2)),"")))`,
        `=IF(E${rowNumber}="","",IF(ISNUMBER(E${rowNumber}),E${rowNumber},IFERROR(DATE(LEFT(E${rowNumber},4),MID(E${rowNumber},6,2),RIGHT(E${rowNumber},2)),"")))`,
      ];
    },
  );
  sheet.getRange(
    `${normalizedStartLabel}${firstDataRow}:${normalizedEndLabel}${lastDataRow}`,
  ).formulas = normalizedDateFormulas;
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
  for (let weekIndex = 0; weekIndex < timelineWeeks; weekIndex += 1) {
    for (const dayOffset of [5, 6]) {
      const weekendLabel = columnLabel(
        firstTimelineColumn + weekIndex * 7 + dayOffset,
      );
      sheet.getRange(
        `${weekendLabel}${firstDataRow}:${weekendLabel}${lastDataRow}`,
      ).format.fill = "#F4F6FA";
    }
  }
  sheet
    .getRange(`I${firstDataRow}:${lastTimelineLabel}${lastDataRow}`)
    .conditionalFormats.addCustom(
      `=AND(I$6>=$${normalizedStartLabel}${firstDataRow},I$6<=$${normalizedStartLabel}${firstDataRow}+ROUND(($${normalizedEndLabel}${firstDataRow}-$${normalizedStartLabel}${firstDataRow}+1)*$F${firstDataRow}/100,0)-1,$B${firstDataRow}<>"")`,
      { fill: colors.cyan },
    );
  sheet
    .getRange(`I${firstDataRow}:${lastTimelineLabel}${lastDataRow}`)
    .conditionalFormats.addCustom(
      `=AND(I$6>=$${normalizedStartLabel}${firstDataRow},I$6<=$${normalizedEndLabel}${firstDataRow},$B${firstDataRow}<>"")`,
      { fill: colors.cyanLight },
    );

  sheet.getRange("A:A").format.columnWidth = 18;
  sheet.getRange("B:B").format.columnWidth = 31;
  sheet.getRange("C:C").format.columnWidth = 24;
  sheet.getRange("D:E").format.columnWidth = 13;
  sheet.getRange("F:F").format.columnWidth = 12;
  sheet.getRange("G:G").format.columnWidth = 15;
  sheet.getRange("H:H").format.columnWidth = 28;
  sheet.getRange(`I:${lastTimelineLabel}`).format.columnWidth = 4.2;
  sheet.getRange(`${normalizedStartLabel}:${normalizedEndLabel}`).format.columnWidth =
    0.1;
  sheet.getRange(`${firstDataRow}:${lastDataRow}`).format.rowHeight = 27;
  sheet.getRange("5:7").format.rowHeight = 22;
  sheet.freezePanes.freezeRows(7);
  sheet.freezePanes.freezeColumns(8);
  sheet.tables.add(`A7:H${lastDataRow}`, true, `${sheet.name.replaceAll(" ", "")}Tasks`);
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
  ["4", "Enter Start Date and End Date.", "Yes", "Excel date or yyyy-mm-dd text", "The calendar, weekday headers, and Gantt bars update automatically. Missing or reversed dates are blocked before import.", "The display starts on the Monday of the earliest task and continues through the latest End Date, up to 53 weeks."],
  ["5", "Enter Progress %.", "No", "0 to 100", "Status is inferred when Status is blank.", "100 becomes Completed."],
  ["6", "Choose Status.", "No", "Not started, In progress, Blocked, Completed", "The selected status is saved to Google Sheets.", ""],
  ["7", "Upload in Project Tracker > Gantt chart.", "Yes", ".xlsx up to 10 MB", "The app shows a preview before any write.", ""],
  ["8", "Confirm the preview.", "Yes", "", "Only prior Excel-imported Gantt tasks for that project are replaced.", "Manual milestones and other projects remain unchanged."],
  ["Tip", "Use the Example sheet as a visual reference.", "", "", "", "Copy only your own rows into Gantt Import. Project start and end cells are calculated from the task dates."],
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
  ["Gantt Import", "A1:CN20"],
  ["Example", "A1:CN20"],
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
  range: "A1:CN14",
  maxChars: 24000,
  tableMaxRows: 14,
  tableMaxCols: 92,
});
const formulaCheck = await workbook.inspect({
  kind: "formula",
  sheetId: "Example",
  range: "A1:CN14",
  maxChars: 24000,
  options: { maxResults: 300 },
});
const tailFormulaCheck = await workbook.inspect({
  kind: "formula",
  sheetId: "Example",
  range: `${columnLabel(lastTimelineColumn - 6)}5:${normalizedEndLabel}14`,
  maxChars: 12000,
  options: { maxResults: 100 },
});
const errors = await workbook.inspect({
  kind: "match",
  searchTerm: formulaErrorPattern,
  options: { useRegex: true, maxResults: 100 },
  summary: "formula error scan",
});
const errorMatches = formulaErrorMatches(errors);
if (errorMatches.length > 0) {
  throw new Error(
    `Formula error scan failed: ${JSON.stringify(errorMatches)}`,
  );
}
console.log(
  JSON.stringify({ check, formulaCheck, tailFormulaCheck, errors }, null, 2),
);

const output = await SpreadsheetFile.exportXlsx(workbook);
await output.save(outputPath);
await fs.copyFile(outputPath, staticPath);
console.log(JSON.stringify({ outputPath, staticPath, previewDir }));
