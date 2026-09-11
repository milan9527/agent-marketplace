import { expect, test } from "@playwright/test";
import type { Agent, Task } from "../src/types";

test("shared test tasks expose bids and downloads without write controls", async ({
  page,
}, info) => {
  const now = new Date().toISOString();
  const agent: Agent = {
    id: "shared-analyst",
    name: "Shared Revenue Analyst",
    tagline: "Business analysis from supplied inputs.",
    description: "A shared specialist profile for a completed test scenario.",
    category: "Finance",
    skills: ["Revenue analysis"],
    price: "0.010000",
    wallet: `0x${"1".repeat(40)}`,
    color: "orange",
    icon: "chart",
    featured: false,
    active: true,
    completed_tasks: 1,
    rating: null,
    review_count: 0,
    created_at: now,
    read_only: true,
  };
  const payment = {
    id: "shared-payment",
    task_id: "shared-task",
    task_title: "Shared commerce review",
    agent_name: agent.name,
    amount: "0.010000",
    status: "settled",
    provider: "agentcore",
    transaction_hash: `0x${"a".repeat(64)}`,
    error: null,
    created_at: now,
    read_only: true,
  };
  const task: Task = {
    id: "shared-task",
    title: "Shared commerce review",
    spec: "Analyze the supplied synthetic commerce data.",
    category: "Finance",
    budget: "0.010000",
    status: "completed",
    deadline: now,
    created_at: now,
    selection_mode: "auto",
    selection_reason: "Automatically selected the highest qualifying bid.",
    winner_id: agent.id,
    bids: [
      {
        id: "shared-bid",
        agent,
        price: "0.010000",
        match_score: 95,
        quality_score: 80,
        rationale: "Strong fit for this commerce analysis.",
        within_budget: true,
        value_score: 0.76,
      },
    ],
    delivery: "# Reviewed commerce result\n\nContribution: USD 8,617.50.",
    rating: null,
    payment,
    read_only: true,
  };
  const writes: string[] = [];
  await page.addInitScript(() =>
    sessionStorage.setItem("access_token", "showcase-test-token"),
  );
  await page.route("**/api/**", async (route) => {
    const request = route.request();
    const path = new URL(request.url()).pathname;
    if (request.method() !== "GET") writes.push(path);
    const body: Record<string, unknown> = {
      "/api/config": {
        mode: "aws",
        network: "Base Sepolia",
        cognito_region: "us-east-1",
        cognito_client_id: "test",
        cognito_domain: "",
        runtime: "Amazon Bedrock AgentCore",
        payments: "AgentCore Payments",
        chain_sync: false,
      },
      "/api/me": {
        id: "showcase-user",
        name: "Marketplace Demo",
        budget: "1",
        spent: "0",
        reserved: "0",
        remaining: "1",
        wallet_connected: true,
        wallet_shared: true,
        payment_limit: "1",
        wallet_url: null,
        wallet_address: null,
        wallet_provider: "Stripe / Privy",
      },
      "/api/me/wallet": {
        provider: "Stripe / Privy",
        status: "ACTIVE",
        balance: "19.838",
        address: `0x${"2".repeat(40)}`,
        network: "Base Sepolia",
        wallet_url: null,
      },
      "/api/agents": [agent],
      "/api/tasks": [task],
      "/api/tasks/shared-task": task,
      "/api/payments": [payment],
      "/api/overview": {
        agents: 1,
        tasks: 1,
        completed: 1,
        spent: "0",
        events: [],
      },
    };
    await route.fulfill({ json: body[path] ?? {} });
  });
  await page.goto("/#tasks");
  await expect(
    page.getByText("Shared test tasks.", { exact: true }),
  ).toBeVisible();
  await page.getByRole("button", { name: /Shared commerce review/ }).click();
  const dialog = page.getByRole("dialog");
  await expect(dialog.getByText("Shared demo task · Read only.")).toBeVisible();
  await expect(
    dialog.getByRole("heading", { name: "Bid history" }),
  ).toBeVisible();
  await expect(dialog.getByText("95% match", { exact: false })).toBeVisible();
  await expect(
    dialog.getByRole("button", { name: /Rate \d stars/ }),
  ).toHaveCount(0);
  await expect(
    dialog.getByRole("button", {
      name: /Pay .*authorize|Choose.*agent|Get deliverable/,
    }),
  ).toHaveCount(0);
  const download = page.waitForEvent("download");
  await dialog.getByRole("button", { name: "Download" }).click();
  expect((await download).suggestedFilename()).toBe("delivery-shared-task.md");
  await page.screenshot({
    path: `../artifacts/showcase-${info.project.name}.png`,
    fullPage: true,
  });
  expect(writes).toEqual([]);
  await dialog.getByRole("button", { name: "Close dialog" }).click();
  await page.goto("/#payments");
  await expect(
    page.getByText("Shared test transaction", { exact: true }),
  ).toBeVisible();
  await expect(page.getByText("0 successful transactions")).toBeVisible();
  await page.getByRole("button", { name: "Stripe / Privy wallet" }).click();
  await expect(page.getByRole("dialog").getByText(/Shared test wallet/)).toContainText(
    "Your account has a total allowance of 1.00 USDC",
  );
  expect(writes).toEqual([]);
});
