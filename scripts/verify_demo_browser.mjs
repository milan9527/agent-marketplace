import { createHash } from "node:crypto";
import { readFile, writeFile } from "node:fs/promises";
import { createRequire } from "node:module";
import path from "node:path";
import { fileURLToPath } from "node:url";

const root = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "..");
const require = createRequire(path.join(root, "frontend/package.json"));
const { chromium, devices, expect } = require("@playwright/test");
const credentials = JSON.parse(await readFile(process.argv[2], "utf8"));
const verification = JSON.parse(
  await readFile(
    path.join(root, "artifacts/aws-demo-verification.json"),
    "utf8",
  ),
);
const site = "https://dp7428wrh61ns.cloudfront.net";
const selected = verification.tasks.find(
  (task) => task.title === "Northstar | Weekly commerce performance review",
);
const browser = await chromium.launch();
const report = [];
try {
  for (const name of ["desktop", "mobile"]) {
    const options =
      name === "desktop"
        ? { viewport: { width: 1440, height: 1050 } }
        : devices["iPhone 13"];
    const context = await browser.newContext(options);
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
    await expect(
      page.getByRole("heading", { name: "Welcome back." }),
    ).toBeVisible();
    await page.getByLabel("Email address").fill(credentials.email);
    await page
      .getByLabel("Password", { exact: true })
      .fill(credentials.password);
    await page.getByRole("button", { name: "Sign in", exact: true }).click();
    await expect(
      page.getByRole("heading", { name: "Discover your next advantage." }),
    ).toBeVisible({ timeout: 45000 });
    await expect(page.locator(".agent-card")).toHaveCount(11);
    await page.screenshot({
      path: path.join(root, `artifacts/aws-demo-account-catalog-${name}.png`),
      fullPage: true,
    });
    await page.getByLabel("Search agents").fill("Atlas");
    await page.getByRole("button", { name: "Research", exact: true }).click();
    await page.getByRole("button", { name: "Featured", exact: true }).click();
    await expect(page.locator(".agent-card")).toHaveCount(1);
    if (name === "mobile")
      await page.getByRole("button", { name: "Open navigation" }).click();
    await page.getByRole("button", { name: "My agents", exact: true }).click();
    await expect(page.locator(".agent-card")).toHaveCount(3);
    await expect(page.getByLabel("Search agents")).toHaveValue("");
    await expect(
      page.getByRole("button", { name: "Featured", exact: true }),
    ).toHaveAttribute("aria-pressed", "false");
    await page.screenshot({
      path: path.join(root, `artifacts/aws-demo-my-agents-${name}.png`),
      fullPage: true,
    });
    if (name === "mobile")
      await page.getByRole("button", { name: "Open navigation" }).click();
    await page
      .getByRole("button", { name: "Discover agents", exact: true })
      .click();
    await expect(page.getByLabel("Search agents")).toHaveValue("Atlas");
    await expect(page.locator(".agent-card")).toHaveCount(1);
    await page.goto(site + "/#tasks");
    await expect(page.locator(".task-row")).toHaveCount(
      verification.visible_task_count,
    );
    await page.screenshot({
      path: path.join(root, `artifacts/aws-demo-account-tasks-${name}.png`),
      fullPage: true,
    });
    await page.locator(".task-row").filter({ hasText: selected.title }).click();
    const dialog = page.getByRole("dialog");
    await expect(
      dialog.getByText("Shared demo task · Read only."),
    ).toBeVisible();
    await expect(dialog.locator(".bid-card")).toHaveCount(3);
    await expect(dialog.locator(".markdown")).toContainText("8617.50");
    await expect(
      dialog.getByRole("button", { name: /Rate \d stars/ }),
    ).toHaveCount(0);
    const downloaded = page.waitForEvent("download");
    await dialog.getByRole("button", { name: "Download" }).click();
    const download = await downloaded;
    const destination = path.join(
      root,
      `artifacts/aws-demo-account-download-${name}.md`,
    );
    await download.saveAs(destination);
    const digest = createHash("sha256")
      .update(await readFile(destination))
      .digest("hex");
    expect(digest).toBe(selected.delivery_sha256);
    await dialog.getByRole("button", { name: "Close dialog" }).click();
    await page.goto(site + "/#payments");
    await expect(page.locator("tbody tr")).toHaveCount(
      verification.visible_payment_count,
    );
    await expect(
      page.getByText(
        `${verification.own_settled_payment_count} successful transactions`,
      ),
    ).toBeVisible();
    if (verification.payment_delegate) {
      await page.getByRole("button", { name: "Stripe / Privy wallet" }).click();
      await expect(
        page.getByRole("dialog").getByText(/Shared test wallet/),
      ).toBeVisible({
        timeout: 45000,
      });
      await expect(
        page.getByRole("dialog").getByText(/1\.00 USDC/),
      ).toBeVisible();
      await page.screenshot({
        path: path.join(root, `artifacts/aws-demo-wallet-${name}.png`),
        fullPage: true,
      });
      await page.keyboard.press("Escape");
    }
    await page.screenshot({
      path: path.join(root, `artifacts/aws-demo-account-payments-${name}.png`),
      fullPage: true,
    });
    await page.goto(site + "/#agents");
    await expect(page.locator(".agent-card")).toHaveCount(3);
    await page.goto(site + "/#tasks");
    await page.reload();
    await expect(page.locator(".task-row")).toHaveCount(
      verification.visible_task_count,
    );
    expect(writes).toEqual([]);
    report.push({
      viewport: name,
      real_password_login: true,
      visible_agents: 11,
      shared_business_agents: 3,
      discover_filters_do_not_hide_my_agents: true,
      shared_tasks: 5,
      shared_payments: 3,
      shared_wallet_verified: verification.payment_delegate,
      downloaded_document_matches: true,
      reload_preserves_access: true,
      marketplace_write_requests: writes,
    });
    await context.close();
  }
} finally {
  await browser.close();
}
await writeFile(
  path.join(root, "artifacts/aws-demo-browser-verification.json"),
  JSON.stringify(report, null, 2) + "\n",
);
console.log(JSON.stringify(report, null, 2));
