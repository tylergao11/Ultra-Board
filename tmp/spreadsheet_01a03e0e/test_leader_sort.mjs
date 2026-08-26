import { chromium } from "playwright";
import { pathToFileURL } from "node:url";

const htmlPath = "C:/Users/84720/.codex/visualizations/2026/08/26/01a03e0e-37ad-73a2-905b-3c2f03271575/leader-sort-table-standalone.html";
const screenshotPath = "C:/Users/84720/.codex/visualizations/2026/08/26/01a03e0e-37ad-73a2-905b-3c2f03271575/leader-sort-table-test.png";
const browser = await chromium.launch({
  headless: true,
  executablePath: "C:/Program Files/Google/Chrome/Application/chrome.exe",
});
const page = await browser.newPage({ viewport: { width: 1024, height: 900 } });
await page.goto(pathToFileURL(htmlPath).href);

const frame = page.frameLocator("iframe");
const rowCount = await frame.locator("tbody tr").count();
if (rowCount !== 95) throw new Error(`expected 95 rows, got ${rowCount}`);

const firstRow = async () => frame.locator("tbody tr").first().locator("td").allTextContents();
const initial = await firstRow();
if (initial[0] !== "2025-01-02") throw new Error(`initial date sort failed: ${initial.join("|")}`);

await frame.getByRole("button", { name: /^股价（元）/ }).click();
const priceAsc = await firstRow();
if (priceAsc[1] !== "香江控股" || priceAsc[3] !== "1.91") throw new Error(`price asc failed: ${priceAsc.join("|")}`);

await frame.getByRole("button", { name: /^股价（元）/ }).click();
const priceDesc = await firstRow();
if (priceDesc[1] !== "大元泵业" || priceDesc[3] !== "32.19") throw new Error(`price desc failed: ${priceDesc.join("|")}`);

await frame.getByRole("button", { name: /^流通市值/ }).click();
const capAsc = await firstRow();
if (capAsc[1] !== "冀凯股份" || capAsc[4] !== "6.30") throw new Error(`cap asc failed: ${capAsc.join("|")}`);

await frame.getByRole("button", { name: /^前十大流通股东合计/ }).click();
const holdersAsc = await firstRow();
if (holdersAsc[1] !== "神剑股份" || holdersAsc[5] !== "25.94%") throw new Error(`holders asc failed: ${holdersAsc.join("|")}`);

await page.screenshot({ path: screenshotPath, fullPage: false });
console.log(JSON.stringify({ rowCount, initial, priceAsc, priceDesc, capAsc, holdersAsc, screenshotPath }, null, 2));
await browser.close();
