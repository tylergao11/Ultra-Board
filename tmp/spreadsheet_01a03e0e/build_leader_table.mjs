import fs from "node:fs/promises";
import { SpreadsheetFile, Workbook } from "@oai/artifact-tool";

if (process.argv.includes("--help-autofilter")) {
  const helpWorkbook = Workbook.create();
  console.log(helpWorkbook.help("*", {
    search: "autoFilter|filter",
    include: "index,examples,notes",
    maxChars: 5000,
  }).ndjson);
  process.exit(0);
}

const inputPath = "C:/Ai/Ultra-Board/tmp/batch_stock_stats_results.json";
const outputDir = "C:/Ai/Ultra-Board/outputs/01a03e0e-37ad-73a2-905b-3c2f03271575";
const outputPath = `${outputDir}/大龙头样本95只_可排序.xlsx`;
const previewMainPath = `${outputDir}/大龙头样本95只_预览.png`;
const previewNotesPath = `${outputDir}/大龙头样本95只_口径说明预览.png`;

const raw = JSON.parse(await fs.readFile(inputPath, "utf8"));
const excluded = new Set([
  "2025-02-27|天正电气",
  "2025-04-08|中源家居",
  "2025-04-10|泰慕士",
  "2025-05-28|御银股份",
  "2025-07-07|四方新材",
  "2025-08-04|国机精工",
  "2025-11-17|榕基软件",
  "2025-12-22|安通股份",
  "2026-05-06|大唐发电",
  "2026-06-15|旭光电子",
  "2026-08-04|宝鼎科技",
]);

const rows = raw.results
  .filter((row) => !excluded.has(`${row.date}|${row.name}`))
  .map((row) => ({ ...row }));

rows.push({
  date: "2025-05-27",
  name: "德邦股份",
  code: "603056",
  price: 15.63,
  float_cap_yi: 38.09,
  top10_pct: 82.57,
});

for (const row of rows) {
  if (row.date === "2025-03-12" && row.name === "奇精机械") {
    row.top10_pct = 74.69;
  }
}

rows.sort((a, b) => a.date.localeCompare(b.date) || a.name.localeCompare(b.name, "zh-CN"));

if (rows.length !== 95) {
  throw new Error(`样本数量应为95，实际为${rows.length}`);
}
for (const row of rows) {
  if (excluded.has(`${row.date}|${row.name}`)) {
    throw new Error(`已删除样本仍存在：${row.date} ${row.name}`);
  }
}

const toDate = (text) => {
  const [year, month, day] = text.split("-").map(Number);
  return new Date(Date.UTC(year, month - 1, day));
};

const workbook = Workbook.create();
const sheet = workbook.worksheets.add("大龙头样本");
const notes = workbook.worksheets.add("口径说明");

const headers = [["日期", "股票名称", "股票代码", "股价（元）", "流通市值（亿元）", "前十大流通股东合计"]];
const data = rows.map((row) => [
  toDate(row.date),
  row.name,
  Number(row.code),
  Number(row.price),
  Number(row.float_cap_yi),
  Number(row.top10_pct) / 100,
]);

sheet.getRange(`A1:F${data.length + 1}`).values = [...headers, ...data];
const table = sheet.tables.add(`A1:F${data.length + 1}`, true, "LeaderSamplesTable");
table.style = "TableStyleMedium2";
table.showHeaders = true;
table.showFilterButton = true;

sheet.showGridLines = false;
sheet.freezePanes.freezeRows(1);
sheet.freezePanes.freezeColumns(3);

const used = sheet.getRange(`A1:F${data.length + 1}`);
used.format.font = { name: "Microsoft YaHei", size: 10, color: "#1F2937" };
used.format.rowHeight = 22;
sheet.getRange("A1:F1").format = {
  fill: "#1F4E78",
  font: { name: "Microsoft YaHei", size: 10, bold: true, color: "#FFFFFF" },
  horizontalAlignment: "center",
  verticalAlignment: "center",
  borders: { preset: "outside", style: "thin", color: "#17365D" },
};
sheet.getRange("A1:F1").format.rowHeight = 28;
sheet.getRange(`A2:A${data.length + 1}`).format.numberFormat = "yyyy-mm-dd";
sheet.getRange(`C2:C${data.length + 1}`).format.numberFormat = "000000";
sheet.getRange(`D2:E${data.length + 1}`).format.numberFormat = "0.00";
sheet.getRange(`F2:F${data.length + 1}`).format.numberFormat = "0.00%";
sheet.getRange(`A2:C${data.length + 1}`).format.horizontalAlignment = "center";
sheet.getRange(`D2:F${data.length + 1}`).format.horizontalAlignment = "right";
sheet.getRange("A:A").format.columnWidth = 13;
sheet.getRange("B:B").format.columnWidth = 14;
sheet.getRange("C:C").format.columnWidth = 12;
sheet.getRange("D:D").format.columnWidth = 13;
sheet.getRange("E:E").format.columnWidth = 19;
sheet.getRange("F:F").format.columnWidth = 24;

notes.showGridLines = false;
notes.getRange("A1:B1").merge();
notes.getRange("A1").values = [["大龙头样本表口径说明"]];
notes.getRange("A1:B1").format = {
  fill: "#1F4E78",
  font: { name: "Microsoft YaHei", size: 14, bold: true, color: "#FFFFFF" },
  horizontalAlignment: "left",
  verticalAlignment: "center",
};
notes.getRange("A1:B1").format.rowHeight = 34;
notes.getRange("A3:B9").values = [
  ["有效样本数", 95],
  ["样本性质", "用户确认的周期大龙头、且具备实际接力可能的样本"],
  ["日期口径", "用户提供的节点日期"],
  ["股价与流通市值", "节点日开盘啦涨停池快照"],
  ["股东合计口径", "节点日当时已经披露的最近一期前十大流通股东持股比例合计"],
  ["股东数据来源", "https://datacenter-web.eastmoney.com/api/data/v1/get"],
  ["未纳入", "2025-11-15 实达集团：当天为周六，未确认正确交易日期"],
];
notes.getRange("A11:B11").merge();
notes.getRange("A11").values = [["用户明确删除的不可接力案例"]];
notes.getRange("A11:B11").format = {
  fill: "#D9EAF7",
  font: { name: "Microsoft YaHei", size: 10, bold: true, color: "#1F2937" },
};
notes.getRange("A12:B22").values = [
  ["2025-02-27", "天正电气"],
  ["2025-04-08", "中源家居"],
  ["2025-04-10", "泰慕士"],
  ["2025-05-28", "御银股份"],
  ["2025-07-07", "四方新材"],
  ["2025-08-04", "国机精工"],
  ["2025-11-17", "榕基软件"],
  ["2025-12-22", "安通股份"],
  ["2026-05-06", "大唐发电"],
  ["2026-06-15", "旭光电子"],
  ["2026-08-04", "宝鼎科技"],
];
notes.getRange("A3:A9").format = {
  fill: "#EAF2F8",
  font: { name: "Microsoft YaHei", size: 10, bold: true, color: "#1F2937" },
};
notes.getRange("A3:B22").format.font = { name: "Microsoft YaHei", size: 10, color: "#1F2937" };
notes.getRange("A3:B22").format.borders = { preset: "inside", style: "thin", color: "#D9E2F3" };
notes.getRange("A3:A22").format.columnWidth = 24;
notes.getRange("B3:B22").format.columnWidth = 72;
notes.getRange("B3:B22").format.wrapText = true;
notes.getRange("A3:B22").format.rowHeight = 24;
notes.freezePanes.freezeRows(1);

const firstInspect = await workbook.inspect({
  kind: "table",
  range: "大龙头样本!A1:F12",
  include: "values,formulas",
  tableMaxRows: 12,
  tableMaxCols: 6,
  maxChars: 5000,
});
const lastInspect = await workbook.inspect({
  kind: "table",
  range: "大龙头样本!A90:F96",
  include: "values,formulas",
  tableMaxRows: 7,
  tableMaxCols: 6,
  maxChars: 3500,
});
const errors = await workbook.inspect({
  kind: "match",
  searchTerm: "#REF!|#DIV/0!|#VALUE!|#NAME\\?|#N/A",
  options: { useRegex: true, maxResults: 100 },
  summary: "final formula error scan",
  maxChars: 2500,
});

await fs.mkdir(outputDir, { recursive: true });
const mainPreview = await workbook.render({ sheetName: "大龙头样本", range: "A1:F24", scale: 1.5, format: "png" });
await fs.writeFile(previewMainPath, new Uint8Array(await mainPreview.arrayBuffer()));
const notesPreview = await workbook.render({ sheetName: "口径说明", range: "A1:B22", scale: 1.5, format: "png" });
await fs.writeFile(previewNotesPath, new Uint8Array(await notesPreview.arrayBuffer()));

const output = await SpreadsheetFile.exportXlsx(workbook);
await output.save(outputPath);

console.log(JSON.stringify({
  outputPath,
  previewMainPath,
  previewNotesPath,
  rowCount: rows.length,
  firstInspect: firstInspect.ndjson,
  lastInspect: lastInspect.ndjson,
  errors: errors.ndjson,
}, null, 2));
