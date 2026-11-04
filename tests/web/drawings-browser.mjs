// Real browser acceptance against the disposable FreeCAD PDF publication fixture.
import assert from "node:assert/strict";
import { readFile, writeFile } from "node:fs/promises";
import path from "node:path";
import { pathToFileURL } from "node:url";

const directory = process.argv[2];
if (!directory) throw new Error("Pass a disposable PDF fixture directory.");
const config = JSON.parse(await readFile(path.join(directory, "connection.json"), "utf8"));
const { chromium } = await import(pathToFileURL(process.env.FORGEPDM_PLAYWRIGHT || "/tmp/forgepdm-pdf-browser/node_modules/playwright-core/index.mjs"));
const browser = await chromium.launch({ executablePath: "/usr/bin/google-chrome", headless: true, args: ["--no-sandbox", "--disable-dev-shm-usage"] });
const context = await browser.newContext({ viewport: { width: 1440, height: 1000 }, acceptDownloads: true });
const page = await context.newPage();
const report = { browser: browser.version(), checks: [], pageErrors: [], scope: "Real Chrome, disposable server and real FreeCAD-generated PDFs" };
const check = (label, condition) => { assert.ok(condition, label); report.checks.push(label); };
page.on("pageerror", error => report.pageErrors.push(error.message));
const fileRequests = [];
page.on("request", request => { if (new URL(request.url()).pathname.includes("/api/v1/files/")) fileRequests.push({ url: request.url(), authorized: !!request.headers().authorization }); });
await page.addInitScript(() => {
  window.pdfURLCreated = []; window.pdfURLRevoked = []; window.pdfCSP = [];
  const create = URL.createObjectURL.bind(URL), revoke = URL.revokeObjectURL.bind(URL);
  URL.createObjectURL = blob => { const url = create(blob); window.pdfURLCreated.push(url); return url; };
  URL.revokeObjectURL = url => { window.pdfURLRevoked.push(url); return revoke(url); };
  document.addEventListener("securitypolicyviolation", event => window.pdfCSP.push(event.violatedDirective));
});
async function open(item, revision) {
  await page.evaluate(({ id, revision }) => { location.hash = new URLSearchParams({ item: id, revision }).toString(); }, { id: item.id, revision });
  await page.waitForFunction(revision => document.querySelector("#revision-picker")?.value === revision, revision);
  await page.getByRole("tab", { name: "Drawings", exact: true }).click();
}
try {
  await page.goto(config.url + "/app/");
  await page.locator("#username").fill(config.username);
  await page.locator("#password").fill(config.password);
  await page.locator("#login-button").click();
  await page.locator("#workspace").waitFor({ state: "visible" });
  await open(config.part, config.part.revision);
  await page.locator("#drawing-page").waitFor();
  check("published pages appear on exact historical revision", await page.locator("#drawing-page option").count() === 2 && await page.locator("#revision-picker").inputValue() === config.part.revision);
  check("newer native snapshot warning is visible", (await page.locator(".drawing-publication .revision-note").innerText()).includes("Newer CAD snapshot"));
  check("source association is shown in advanced details", (await page.locator(".drawing-source details").textContent()).includes(config.publication.source_file_id));
  await page.getByRole("button", { name: "Preview PDF", exact: true }).click();
  await page.locator("iframe.pdf-frame").waitFor();
  const firstURL = await page.locator("iframe.pdf-frame").getAttribute("src");
  check("preview uses a PDF Blob URL instead of a bearer query", firstURL.startsWith("blob:") && !firstURL.includes("token"));
  await page.waitForTimeout(1000);
  const frame = page.frames().find(frame => frame.url() === firstURL);
  check("PDF browser frame loads", !!frame);
  check("PDF is handed to the native browser viewer", await frame.evaluate(() => document.contentType) === "application/pdf" || page.frames().some(f => f.url().startsWith("chrome-extension:")));
  check("PDF preview does not violate CSP", (await page.evaluate(() => window.pdfCSP)).length === 0);
  await page.locator("iframe.pdf-frame").scrollIntoViewIfNeeded();
  await page.waitForTimeout(500);
  await page.screenshot({ path: path.join(directory, "drawings-desktop.png"), fullPage: true });
  const second = await page.locator("#drawing-page option").nth(1).getAttribute("value");
  await page.locator("#drawing-page").selectOption(second);
  check("changing pages clears old preview", await page.locator("iframe.pdf-frame").count() === 0);
  check("old page Blob URL is revoked", await page.evaluate(url => window.pdfURLRevoked.includes(url), firstURL));
  await page.getByRole("button", { name: "Preview PDF", exact: true }).click();
  await page.locator("iframe.pdf-frame").waitFor();
  const downloadReady = page.waitForEvent("download");
  await page.getByRole("button", { name: "Download PDF", exact: true }).click();
  const download = await downloadReady;
  const bytes = await readFile(await download.path());
  check("PDF download contains real PDF bytes", bytes.subarray(0, 5).toString() === "%PDF-" && download.suggestedFilename().endsWith(".pdf"));
  check("all PDF API reads use authorization headers", fileRequests.length >= 3 && fileRequests.every(request => request.authorized && !new URL(request.url).search));
  await page.setViewportSize({ width: 390, height: 844 });
  await page.locator("iframe.pdf-frame").scrollIntoViewIfNeeded();
  await page.waitForTimeout(1000);
  await page.screenshot({ path: path.join(directory, "drawings-mobile.png"), fullPage: true });
  check("mobile layout stays within viewport", await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth + 1));
  const previous = await page.locator("iframe.pdf-frame").getAttribute("src");
  await page.getByRole("tab", { name: "Overview", exact: true }).click();
  check("tab navigation revokes preview bytes", await page.evaluate(url => window.pdfURLRevoked.includes(url), previous));
  await open(config.assembly, config.assembly.revision);
  await page.locator("#drawing-page").waitFor();
  check("assembly publication has its own page", await page.locator("#drawing-page option").count() === 1);
  check("exact assembly snapshot stays current despite a newer child upload", await page.locator(".drawing-publication .revision-note").count() === 0);
  await open(config.part, config.part.next_revision);
  await page.getByText("No drawing PDFs have been published for this revision.", { exact: true }).waitFor();
  check("new revision never inherits old drawing PDFs", await page.locator("#drawing-page").count() === 0);
  await open(config.part, config.part.revision);
  await page.locator("#drawing-page").waitFor();
  await page.getByRole("button", { name: "Preview PDF", exact: true }).click();
  await page.locator("iframe.pdf-frame").waitFor();
  const logoutURL = await page.locator("iframe.pdf-frame").getAttribute("src");
  await page.locator("#logout").click();
  await page.locator("#login-screen").waitFor({ state: "visible" });
  check("logout removes protected preview and revokes Blob URL", await page.locator("iframe.pdf-frame").count() === 0 && await page.evaluate(url => window.pdfURLRevoked.includes(url), logoutURL));
  check("no unhandled browser errors", report.pageErrors.length === 0);
  report.status = "passed";
} catch (error) {
  report.status = "failed"; report.error = error.message;
  await page.screenshot({ path: path.join(directory, "drawings-failure.png"), fullPage: true });
  throw error;
} finally {
  await writeFile(path.join(directory, "drawings-browser-report.json"), JSON.stringify(report, null, 2) + "\n");
  await browser.close();
}
