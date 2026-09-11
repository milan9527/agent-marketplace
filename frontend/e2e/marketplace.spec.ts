import { expect, test } from "@playwright/test";

test("browse, compare bids, pay, receive a delivery, and leave a review", async ({
  page,
}) => {
  const errors: string[] = [];
  page.on("pageerror", (e) => errors.push(e.message));
  await page.goto("/");
  await expect(
    page.getByRole("heading", { name: "Discover your next advantage." }),
  ).toBeVisible();
  await expect(page.locator(".agent-card")).toHaveCount(8);
  expect(await page.locator("body").innerText()).not.toMatch(/[\u3400-\u9fff]/);
  await page.screenshot({
    path: "test-results/marketplace-desktop.png",
    fullPage: true,
  });
  await page.getByRole("button", { name: "Finance", exact: true }).click();
  await expect(page.locator(".agent-card")).toHaveCount(2);
  await page.getByRole("button", { name: /All agents/ }).click();
  await page.getByRole("textbox", { name: "Search agents" }).fill("CodeCraft");
  await expect(page.locator(".agent-card")).toHaveCount(1);
  await page.getByRole("button", { name: "Clear search" }).click();
  await page.getByRole("button", { name: "Post a task", exact: true }).click();
  const title = `Research cloud developer tools ${Date.now()}`;
  await page.getByLabel("Task title").fill(title);
  await page
    .getByLabel("Your brief")
    .fill(
      "Compare the positioning of three cloud developer tools. Identify strengths, risks, and useful evaluation criteria.",
    );
  await page.getByLabel("Maximum budget (USDC)").fill("0.05");
  await page.getByRole("button", { name: "Post task & get bids" }).click();
  await expect(page.getByText("8 specialists. Your choice.")).toBeVisible();
  await page.getByRole("button", { name: "Choose agent" }).first().click();
  await expect(page.getByText("Your chosen specialist")).toBeVisible();
  await page.getByRole("button", { name: /Pay \$.* & authorize/ }).click();
  await expect(page.getByText("Payment confirmed.")).toBeVisible();
  await page.getByRole("button", { name: "Get deliverable" }).click();
  await expect(page.getByText("Your outcome, delivered.")).toBeVisible();
  await page.getByRole("button", { name: "Rate 5 stars", exact: true }).click();
  await expect(
    page.getByText("Thanks for sharing your experience."),
  ).toBeVisible();
  await page.screenshot({
    path: "test-results/marketplace-delivery.png",
    fullPage: true,
  });
  await page.getByRole("button", { name: "Close dialog" }).click();
  await page.getByRole("button", { name: "Payments", exact: true }).click();
  await expect(
    page.getByRole("button", { name: title, exact: true }),
  ).toBeVisible();
  await expect(page.getByText("Demo receipt").first()).toBeVisible();
  const downloaded = page.waitForEvent("download");
  await page.getByRole("button", { name: "Export history" }).click();
  expect((await downloaded).suggestedFilename()).toBe(
    "marketplace-payments.csv",
  );
  await page.getByRole("button", { name: "Connect existing wallet" }).click();
  await expect(page.getByRole("dialog")).toContainText(
    "existing Stripe/Privy wallet",
  );
  await expect(
    page.getByRole("button", { name: "Create payment wallet" }),
  ).toHaveCount(0);
  await page.getByRole("button", { name: "Got it" }).click();
  expect(errors).toEqual([]);
});

test("settings save spending limit and dialogs are keyboard accessible", async ({
  page,
}) => {
  await page.goto("/#settings");
  await expect(
    page.getByRole("heading", { name: "Workspace settings" }),
  ).toBeVisible();
  await page.getByLabel("Total spending limit (USDC)").fill("12");
  await page.getByRole("button", { name: "Save spending limit" }).click();
  await expect(
    page.getByRole("status").filter({ hasText: "Spending limit updated." }),
  ).toBeVisible();
  await page.getByRole("button", { name: "How it works" }).click();
  await expect(page.getByRole("dialog")).toBeVisible();
  await page.keyboard.press("Escape");
  await expect(page.getByRole("dialog")).toHaveCount(0);
});
