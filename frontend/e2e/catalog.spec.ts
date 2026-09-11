import { expect, test } from "@playwright/test";

test("new users can browse demo profiles and start a demo task", async ({
  page,
}, info) => {
  const ids = [
    "atlas",
    "finley",
    "codecraft",
    "quill",
    "prism",
    "relay",
    "marcus",
    "scout",
  ];
  await page.route("**/api/agents**", async (route) => {
    if (new URL(route.request().url()).searchParams.get("mine") === "true") {
      return route.fulfill({ json: [] });
    }
    const agents = await (await route.fetch()).json();
    return route.fulfill({
      json: agents
        .filter((agent: { id: string }) => ids.includes(agent.id))
        .map((agent: object) => ({
          ...agent,
          is_demo: true,
          bookable: true,
          wallet: null,
          rating: null,
          completed_tasks: 0,
          review_count: 0,
        })),
    });
  });
  await page.route("**/api/tasks", (route) => route.fulfill({ json: [] }));
  await page.route("**/api/payments", (route) => route.fulfill({ json: [] }));
  await page.route("**/api/overview", (route) =>
    route.fulfill({
      json: { agents: 8, tasks: 0, completed: 0, spent: "0", events: [] },
    }),
  );
  await page.goto("/");
  await expect(page.getByText("Explore the demo catalog.")).toBeVisible();
  await expect(
    page.getByRole("button", { name: "Try agent", exact: true }),
  ).toHaveCount(8);
  await expect(
    page.getByRole("button", { name: "Hire agent", exact: true }),
  ).toHaveCount(0);
  expect(
    await page.evaluate(
      () => document.documentElement.scrollWidth <= innerWidth,
    ),
  ).toBeTruthy();
  await page.screenshot({
    path: `test-results/demo-catalog-${info.project.name}.png`,
    fullPage: true,
  });
  await page.getByRole("button", { name: "Finance", exact: true }).click();
  await expect(
    page.getByRole("button", { name: "Try agent", exact: true }),
  ).toHaveCount(2);
  await page.getByRole("button", { name: /^All agents/ }).click();
  await page.getByLabel("Search agents").fill("CodeCraft");
  await expect(
    page.getByRole("button", { name: "Try agent", exact: true }),
  ).toHaveCount(1);
  await page.getByRole("button", { name: "CodeCraft", exact: true }).click();
  const dialog = page.getByRole("dialog");
  await expect(dialog.getByText("Demo profile", { exact: true })).toBeVisible();
  await expect(dialog.getByText("Not needed for demo runs")).toBeVisible();
  await expect(dialog.getByRole("button", { name: /^Work with/ })).toHaveCount(
    0,
  );
  await dialog
    .getByRole("button", { name: "Try CodeCraft", exact: true })
    .click();
  await expect(
    page.getByRole("heading", { name: "Try CodeCraft" }),
  ).toBeVisible();
  await expect(page.getByLabel("Your brief")).toBeVisible();
  await page.getByRole("button", { name: "Close dialog" }).click();
  if (info.project.name === "mobile")
    await page.getByRole("button", { name: "Open navigation" }).click();
  await page.getByRole("button", { name: /^My agents/ }).click();
  await expect(
    page.getByRole("heading", { name: "No agents found" }),
  ).toBeVisible();
});
