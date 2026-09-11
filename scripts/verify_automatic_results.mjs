// Read and download the completed automatic tasks without creating new payments.
import { createHash } from "node:crypto";
import { readFile, writeFile } from "node:fs/promises";
import { createRequire } from "node:module";
import path from "node:path";
import { fileURLToPath } from "node:url";

const root = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "..");
const require = createRequire(path.join(root, "frontend/package.json"));
const { chromium, devices, expect } = require("@playwright/test");
const credentials = JSON.parse(await readFile(process.argv[2], "utf8"));
const directory = path.join(root, "artifacts/automatic-workflow");
const verification = JSON.parse(
  await readFile(path.join(directory, "verification.json"), "utf8"),
);
expect(verification.verified).toBe(true);
const outputs = JSON.parse(
  await readFile(path.join(root, "artifacts/aws-outputs.json"), "utf8"),
).AgentMarketplace;
const site = outputs.WebsiteUrl;
const report = [];
const browser = await chromium.launch();
try {
  for (const name of ["desktop", "mobile"]) {
    const context = await browser.newContext(
      name === "desktop"
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
    for (const task of Object.values(verification.tasks)) {
      await page.locator(".task-row").filter({ hasText: task.title }).click();
      const dialog = page.getByRole("dialog");
      await expect(
        dialog.getByText("Task completed", { exact: true }),
      ).toBeVisible();
      await expect(dialog.locator(".markdown")).toBeVisible();
      await expect(
        dialog.getByRole("button", {
          name: /Pay & authorize|Get deliverable|Run automatically/,
        }),
      ).toHaveCount(0);
      const pending = page.waitForEvent("download");
      await dialog
        .getByRole("button", { name: "Download", exact: true })
        .click();
      const downloaded = await pending;
      const destination = path.join(directory, `${task.id}-${name}.md`);
      await downloaded.saveAs(destination);
      const digest = createHash("sha256")
        .update(await readFile(destination))
        .digest("hex");
      expect(digest).toBe(task.delivery_sha256);
      await page.screenshot({
        path: path.join(directory, `${task.id}-${name}.png`),
        fullPage: true,
      });
      checked.push(task.id);
      await dialog.getByRole("button", { name: "Close dialog" }).click();
    }
    expect(writes).toEqual([]);
    report.push({
      viewport: name,
      completed_tasks: checked,
      downloads_verified: true,
      write_requests: writes,
    });
    await context.close();
  }
} finally {
  await browser.close();
}
await writeFile(
  path.join(directory, "browser-results.json"),
  JSON.stringify(report, null, 2) + "\n",
);
console.log(JSON.stringify(report, null, 2));
