import fs from "node:fs/promises";

import { FileBlob, SpreadsheetFile } from "@oai/artifact-tool";

const samplePath =
  "/Users/kkamei/Downloads/TF4bf6b793-490f-4623-84ca-c9c6251a91fcccfc8a17_wac-90da771544e0.xlsx";

const blob = await FileBlob.load(samplePath);
const workbook = await SpreadsheetFile.importXlsx(blob);
const overview = await workbook.inspect({
  kind: "workbook",
  include: "id,name",
});
const sheets = await workbook.inspect({
  kind: "sheet",
  include: "id,name",
});
const projectSchedule = await workbook.inspect({
  kind: "region",
  sheetId: "Project schedule",
  range: "A1:BL33",
  maxChars: 30000,
});
const taskTable = await workbook.inspect({
  kind: "table",
  sheetId: "Project schedule",
  range: "A5:H33",
  maxChars: 24000,
  tableMaxRows: 40,
  tableMaxCols: 8,
  tableMaxCellChars: 120,
});
const formulas = await workbook.inspect({
  kind: "formula",
  sheetId: "Project schedule",
  range: "A1:BL33",
  maxChars: 12000,
  options: { maxResults: 200 },
});
const about = await workbook.inspect({
  kind: "region",
  sheetId: "About",
  range: "A1:A16",
  maxChars: 8000,
});
const preview = await workbook.render({
  sheetName: "Project schedule",
  autoCrop: "all",
  scale: 1,
  format: "png",
});
await fs.writeFile(
  "/private/tmp/kamei-gantt-artifact/project-schedule.png",
  new Uint8Array(await preview.arrayBuffer()),
);

console.log(
  JSON.stringify(
    { overview, sheets, projectSchedule, taskTable, formulas, about },
    null,
    2,
  ),
);
