import { expect, test } from "@playwright/test";
import { readFile } from "node:fs/promises";
import type { Agent, Task } from "../src/types";

test("AWS demo completes without a wallet or payment and preserves the result", async ({
  page,
}, info) => {
  const now = new Date().toISOString();
  const agent: Agent = {
    id: "demo-atlas",
    name: "Atlas Research",
    tagline: "Deep research. Clear answers.",
    description: "Create a useful research brief from supplied information.",
    category: "Research",
    skills: ["Research"],
    price: "0.04",
    wallet: null,
    is_demo: true,
    bookable: true,
    color: "blue",
    icon: "globe",
    featured: true,
    active: true,
    completed_tasks: 0,
    rating: null,
    review_count: 0,
    created_at: now,
  };
  let task: Task | null = null;
  const actions: string[] = [];
  await page.addInitScript(() =>
    sessionStorage.setItem("access_token", "test-access-token"),
  );
  await page.route("**/api/**", async (route) => {
    const request = route.request();
    const url = new URL(request.url());
    const path = url.pathname.replace("/api", "");
    let body: unknown;
    if (path === "/config")
      body = {
        mode: "aws",
        network: "Base Sepolia",
        cognito_region: "us-east-1",
        cognito_client_id: "test",
        cognito_domain: "",
        runtime: "Amazon Bedrock AgentCore",
        payments: "AgentCore Payments",
        chain_sync: false,
      };
    else if (path === "/me")
      body = {
        id: "new-user",
        name: "Demo Builder",
        budget: "10",
        spent: "0",
        reserved: "0",
        remaining: "10",
        wallet_connected: false,
        wallet_url: null,
        wallet_address: null,
        wallet_provider: "Stripe / Privy",
      };
    else if (path === "/agents")
      body = url.searchParams.has("mine") ? [] : [agent];
    else if (path === "/payments") body = [];
    else if (path === "/overview")
      body = {
        agents: 1,
        tasks: task ? 1 : 0,
        completed: task?.status === "completed" ? 1 : 0,
        spent: "0",
        events: [],
      };
    else if (path === "/tasks" && request.method() === "POST") {
      actions.push("create");
      task = {
        ...request.postDataJSON(),
        id: "demo-task",
        status: "open",
        is_demo: false,
        created_at: now,
        winner_id: null,
        bids: [],
        delivery: null,
        rating: null,
        payment: null,
      };
      body = task;
    } else if (path === "/tasks") body = task ? [task] : [];
    else if (path === "/tasks/demo-task") body = task;
    else if (path.startsWith("/tasks/demo-task/") && task) {
      const action = path.split("/").pop()!;
      actions.push(action);
      if (action === "quote")
        task = {
          ...task,
          is_demo: true,
          status: "bidding",
          bids: [
            {
              id: "demo-bid",
              agent,
              price: "0.04",
              match_score: 96,
              quality_score: 80,
              rationale: "I can compare the supplied product information.",
              within_budget: true,
              value_score: 1,
            },
          ],
        };
      else if (action === "select")
        task = { ...task, winner_id: agent.id, status: "demo_ready" };
      else if (action === "deliver") {
        expect(task.status).toBe("demo_ready");
        task = {
          ...task,
          status: "completed",
          delivery:
            "> Demo deliverable · No payment was made.\n\n# Research result\n\nCompare the tools against the supplied criteria.",
        };
      } else if (action === "rate")
        task = { ...task, rating: request.postDataJSON().score };
      else throw new Error(`Unexpected demo action: ${action}`);
      body = task;
    } else throw new Error(`Unexpected API request: ${path}`);
    return route.fulfill({ json: body });
  });
  await page.goto("/");
  await page.getByRole("button", { name: "Post a task", exact: true }).click();
  await page.getByLabel("Task title").fill("Compare developer tools");
  await page
    .getByLabel("Your brief")
    .fill(
      "Compare developer tools against usability and deployment requirements.",
    );
  await page.getByRole("button", { name: "Post task & get bids" }).click();
  await page.getByRole("button", { name: "Choose demo agent" }).click();
  const dialog = page.getByRole("dialog");
  await expect(dialog.getByText("Your demo agent is ready.")).toBeVisible();
  await expect(
    dialog.getByRole("button", { name: /Connect Stripe|Pay \$/ }),
  ).toHaveCount(0);
  await dialog.getByRole("button", { name: "Run demo", exact: true }).click();
  await expect(dialog.getByText("Your outcome, delivered.")).toBeVisible();
  await expect(
    dialog.getByText("Demo deliverable · No payment was made."),
  ).toBeVisible();
  const download = page.waitForEvent("download");
  await dialog.getByRole("button", { name: "Download", exact: true }).click();
  const file = await download;
  await file.saveAs(info.outputPath("demo.md"));
  expect(await readFile(info.outputPath("demo.md"), "utf8")).toContain(
    "No payment was made.",
  );
  await dialog
    .getByRole("button", { name: "Rate 5 stars", exact: true })
    .click();
  await expect(
    dialog.getByText("Thanks for sharing your experience."),
  ).toBeVisible();
  await page.screenshot({
    path: `test-results/demo-workflow-${info.project.name}.png`,
    fullPage: true,
  });
  expect(actions).toEqual(["create", "quote", "select", "deliver", "rate"]);
  await page.getByRole("button", { name: "Close dialog" }).click();
  await page.reload();
  await page.getByRole("button", { name: /Compare developer tools/ }).click();
  await expect(
    page.getByRole("dialog").getByText("Your outcome, delivered."),
  ).toBeVisible();
});
