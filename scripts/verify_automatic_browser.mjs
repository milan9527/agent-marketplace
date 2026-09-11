// Publish one 0.01-test-USDC automatic task, then close the browser.
import { access, readFile, writeFile, mkdir } from "node:fs/promises";
import { createRequire } from "node:module";
import path from "node:path";
import { fileURLToPath } from "node:url";

const root = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "..");
const require = createRequire(path.join(root, "frontend/package.json"));
const { chromium, expect } = require("@playwright/test");
const credentials = JSON.parse(await readFile(process.argv[2], "utf8"));
const outputs = JSON.parse(
  await readFile(path.join(root, "artifacts/aws-outputs.json"), "utf8"),
).AgentMarketplace;
const site = outputs.WebsiteUrl;
const directory = path.join(root, "artifacts/automatic-workflow");
await mkdir(directory, { recursive: true });
const reportPath = path.join(directory, "browser-create.json");
let exists = false;
try {
  await access(reportPath);
  exists = true;
} catch {}
if (exists)
  throw new Error(
    "Inspect the existing verification report before creating another paid task.",
  );

const report = { started_at: new Date().toISOString(), write_requests: [] };
const save = () =>
  writeFile(reportPath, JSON.stringify(report, null, 2) + "\n");
const browser = await chromium.launch();
try {
  const page = await browser.newPage({
    viewport: { width: 1440, height: 1050 },
  });
  page.on("request", (request) => {
    if (
      request.url().startsWith(site + "/api/") &&
      request.method() !== "GET"
    ) {
      report.write_requests.push(new URL(request.url()).pathname);
    }
  });
  await page.goto(site + "/login");
  await page.getByLabel("Email address").fill(credentials.email);
  await page.getByLabel("Password", { exact: true }).fill(credentials.password);
  await page.getByRole("button", { name: "Sign in", exact: true }).click();
  await expect(
    page.getByRole("heading", { name: "Discover your next advantage." }),
  ).toBeVisible({ timeout: 45000 });
  report.account_before = await page.evaluate(async () => {
    const response = await fetch("/api/me", {
      headers: {
        Authorization: "Bearer " + sessionStorage.getItem("access_token"),
      },
    });
    if (!response.ok) throw new Error("Could not read the signed-in account.");
    return response.json();
  });
  expect(report.account_before.id).toBe(credentials.sub);
  expect(report.account_before.wallet_connected).toBe(true);
  expect(Number(report.account_before.remaining)).toBeGreaterThanOrEqual(0.03);
  await page.getByRole("button", { name: "Post a task", exact: true }).click();
  await page
    .getByLabel("Task title")
    .fill("BrightCart | Automatic daily contribution report");
  await page
    .getByLabel("Your brief")
    .fill(
      "BUSINESS SIMULATION: Analyze these synthetic USD figures using supplied data only. " +
        "Paid Search: revenue 5000, COGS 2500, advertising spend 1000. " +
        "Email: revenue 3000, COGS 1200, advertising spend 200. " +
        "Define contribution = revenue - COGS - advertising spend; contribution margin = contribution / revenue; " +
        "ROAS = revenue / advertising spend. Calculate the three metrics for each channel and in total, " +
        "show formulas and a Markdown table, then recommend three next-day actions for channel profitability " +
        "and a USD 1200 marketing allocation that sums exactly to 1200. Explain attribution and saturation limitations. " +
        "Return an English revenue-analysis report; do not claim external data access or execute campaigns.",
    );
  await page
    .getByRole("combobox", { name: "Category", exact: true })
    .selectOption("Finance");
  await page.getByLabel("Maximum budget (USDC)").fill("0.01");
  await page
    .getByRole("combobox", { name: "Accept bids for", exact: true })
    .selectOption("72");
  await page
    .getByRole("combobox", { name: "Agent selection", exact: true })
    .selectOption("auto");
  await page
    .getByRole("combobox", { name: "Agent pool", exact: true })
    .selectOption("live");
  await expect(
    page.getByText(/Publishing an automatic task authorizes/),
  ).toBeVisible();
  await page.screenshot({
    path: path.join(directory, "automatic-task-form.png"),
    fullPage: true,
  });
  await save();
  const responsePromise = page.waitForResponse(
    (response) =>
      response.url() === site + "/api/tasks" &&
      response.request().method() === "POST",
    { timeout: 90000 },
  );
  await page.getByRole("button", { name: "Post task & get bids" }).click();
  const response = await responsePromise;
  expect(response.status()).toBe(201);
  report.task = await response.json();
  expect(report.task.auto_execute).toBe(true);
  expect(report.task.agent_scope).toBe("live");
  expect(report.task.budget).toBe("0.010000");
  await save();
  await page.close();
  report.browser_closed_at = new Date().toISOString();
  expect(report.write_requests).toEqual(["/api/tasks"]);
  await save();
  console.log(
    JSON.stringify({
      task_id: report.task.id,
      initial_status: report.task.status,
      browser_closed: true,
      write_requests: report.write_requests,
    }),
  );
} catch (error) {
  report.error = error.message;
  await save();
  throw error;
} finally {
  await browser.close();
}
