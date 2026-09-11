import { createHash } from "node:crypto";
import { readFile, writeFile } from "node:fs/promises";
import { createRequire } from "node:module";
import path from "node:path";
import { fileURLToPath } from "node:url";

const root = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "..");
const require = createRequire(path.join(root, "frontend/package.json"));
const { chromium, devices, expect } = require("@playwright/test");
const credentials = JSON.parse(await readFile(process.argv[2], "utf8"));
const directory = path.join(root, "artifacts/real-agent-tools");
const verification = JSON.parse(
  await readFile(path.join(directory, "live-verification.json"), "utf8"),
);
if (!verification.verified) throw new Error("Complete API verification first.");
const site = "https://dp7428wrh61ns.cloudfront.net";
const browser = await chromium.launch();
const report = [];
try {
  for (const viewport of ["desktop", "mobile"]) {
    const context = await browser.newContext(
      viewport === "desktop"
        ? { viewport: { width: 1440, height: 1050 } }
        : devices["iPhone 13"],
    );
    const page = await context.newPage();
    const writes = [];
    page.on("request", (request) => {
      if (
        request.url().startsWith(site + "/api/") &&
        request.method() !== "GET"
      ) {
        writes.push(new URL(request.url()).pathname);
      }
    });
    await page.goto(site + "/login");
    await page.getByLabel("Email address").fill(credentials.email);
    await page
      .getByLabel("Password", { exact: true })
      .fill(credentials.password);
    await page.getByRole("button", { name: "Sign in", exact: true }).click();
    await expect(
      page.getByRole("heading", { name: "Discover your next advantage." }),
    ).toBeVisible({ timeout: 45000 });
    await page.goto(site + "/#tasks");
    const checked = [];
    for (const category of ["research", "development"]) {
      const task = verification.tasks[category];
      await page.locator(".task-row").filter({ hasText: task.title }).click();
      const dialog = page.getByRole("dialog");
      const evidence = dialog.getByRole("region", {
        name: "Execution evidence",
      });
      await expect(evidence).toBeVisible();
      await expect(evidence).toContainText(
        "Tools ran and the result passed evidence checks.",
      );
      await expect(evidence.locator(".execution-timeline > li")).toHaveCount(
        task.execution.trace.length,
      );
      await evidence.locator(".execution-timeline summary").first().click();
      await expect(
        evidence.locator(".execution-timeline pre").first(),
      ).toBeVisible();
      if (category === "research") {
        await expect(evidence.locator(".execution-sources a")).toHaveCount(
          task.execution.sources.length,
        );
        await expect(evidence).toContainText("Page read");
        await expect(evidence).toContainText("AgentCore Web Search");
      } else {
        await expect(evidence).toContainText("AgentCore Code Interpreter");
      }
      await evidence
        .getByText("Acceptance checks · Passed", { exact: true })
        .click();
      const file = task.execution.artifacts.find(
        (item) =>
          item.name === (category === "research" ? "report.md" : "tests.py"),
      );
      if (!file) throw new Error("Expected verified output file is missing.");
      const downloaded = page.waitForEvent("download");
      await evidence
        .getByRole("button", {
          name: new RegExp(file.name.replace(".", "\\.")),
        })
        .click();
      const download = await downloaded;
      const destination = path.join(
        directory,
        `browser-${viewport}-${category}-${file.name}`,
      );
      await download.saveAs(destination);
      expect(
        createHash("sha256")
          .update(await readFile(destination))
          .digest("hex"),
      ).toBe(file.sha256);
      await evidence
        .getByRole("heading", { name: "Execution evidence", exact: true })
        .scrollIntoViewIfNeeded();
      await page.screenshot({
        path: path.join(directory, `browser-${viewport}-${category}.png`),
      });
      checked.push({
        category,
        task_id: task.id,
        execution_id: task.execution.id,
        trace_steps: task.execution.trace.length,
        download_sha256: file.sha256,
      });
      await dialog.getByRole("button", { name: "Close dialog" }).click();
    }
    expect(writes).toEqual([]);
    report.push({
      viewport,
      password_login: true,
      checked,
      marketplace_writes: writes,
    });
    await context.close();
  }
} finally {
  await browser.close();
}
await writeFile(
  path.join(directory, "browser-verification.json"),
  JSON.stringify(report, null, 2) + "\n",
);
console.log(JSON.stringify(report, null, 2));
