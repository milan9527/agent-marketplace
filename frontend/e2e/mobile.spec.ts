import { expect, test } from "@playwright/test";

test("responsive browsing and navigation", async ({ page }, testInfo) => {
  test.skip(testInfo.project.name !== "mobile", "Mobile viewport check");
  await page.goto("/");
  await expect(
    page.getByRole("heading", { name: "Discover your next advantage." }),
  ).toBeVisible();
  expect(
    await page.evaluate(
      () => document.documentElement.scrollWidth <= window.innerWidth,
    ),
  ).toBeTruthy();
  await page.screenshot({
    path: "test-results/marketplace-mobile.png",
    fullPage: true,
  });
  await page.getByRole("button", { name: "Open navigation" }).click();
  await page.getByRole("button", { name: "My tasks", exact: false }).click();
  await expect(
    page.getByRole("heading", { name: "My tasks", exact: true }),
  ).toBeVisible();
  await page.getByRole("button", { name: "Post a task" }).click();
  await expect(page.getByRole("dialog")).toBeVisible();
  await expect(page.getByLabel("Your brief")).toBeVisible();
  await page.getByRole("button", { name: "Close dialog" }).click();
});
