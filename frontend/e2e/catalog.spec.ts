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
    page.getByRole("heading", { name: "No agents published yet" }),
  ).toBeVisible();
});

test("Discover filters do not hide My agents, and each catalog keeps its filters", async ({
  page,
}, info) => {
  const errors: string[] = [];
  page.on("pageerror", (error) => errors.push(error.message));
  const base = {
    tagline: "A specialist for your next task.",
    description: "Analyze the supplied inputs.",
    skills: ["Analysis"],
    price: "0.010000",
    wallet: `0x${"1".repeat(40)}`,
    color: "orange",
    icon: "chart",
    active: true,
    bookable: true,
    completed_tasks: 0,
    rating: null,
    review_count: 0,
    created_at: new Date().toISOString(),
  };
  const shared = {
    ...base,
    id: "shared-analyst",
    name: "Shared Revenue Analyst",
    category: "Finance",
    featured: false,
    read_only: true,
  };
  const atlas = {
    ...base,
    id: "atlas",
    name: "Atlas Research",
    category: "Research",
    featured: true,
    is_demo: true,
    wallet: null,
  };
  await page.route("**/api/agents**", (route) =>
    route.fulfill({
      json:
        new URL(route.request().url()).searchParams.get("mine") === "true"
          ? [shared]
          : [atlas, shared],
    }),
  );
  const navigate = async (name: string) => {
    if (info.project.name === "mobile")
      await page.getByRole("button", { name: "Open navigation" }).click();
    await page.getByRole("button", { name, exact: true }).click();
  };
  await page.goto("/");
  await expect(page.locator(".agent-card")).toHaveCount(2);
  await page.getByLabel("Search agents").fill("Atlas");
  await page.getByRole("button", { name: "Research", exact: true }).click();
  await page.getByRole("button", { name: "Featured", exact: true }).click();
  await expect(page.locator(".agent-card")).toHaveCount(1);
  await navigate("My agents");
  await expect(page.locator(".agent-card")).toHaveCount(1);
  await expect(
    page.getByRole("button", { name: shared.name, exact: true }),
  ).toBeVisible();
  await expect(page.getByLabel("Search agents")).toHaveValue("");
  await expect(
    page.getByRole("button", { name: "Featured", exact: true }),
  ).toHaveAttribute("aria-pressed", "false");
  await page.getByLabel("Search agents").fill("No matching specialist");
  await expect(
    page.getByRole("heading", { name: "No agents found" }),
  ).toBeVisible();
  await page
    .getByRole("button", { name: "Clear filters", exact: true })
    .click();
  await expect(page.locator(".agent-card")).toHaveCount(1);
  await navigate("Discover agents");
  await expect(page.getByLabel("Search agents")).toHaveValue("Atlas");
  await expect(
    page.getByRole("button", { name: "Featured", exact: true }),
  ).toHaveAttribute("aria-pressed", "true");
  await expect(page.locator(".agent-card")).toHaveCount(1);
  await page.goBack();
  await expect(
    page.getByRole("heading", { name: "My agents", exact: true }),
  ).toBeVisible();
  await expect(page.locator(".agent-card")).toHaveCount(1);
  expect(errors).toEqual([]);
});
