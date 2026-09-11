import { expect, test } from "@playwright/test";

test("tool progress, source provenance and real output downloads are visible", async ({
  page,
}) => {
  const timestamp = new Date().toISOString();
  const execution = {
    id: "execution-1",
    status: "running",
    steps: 2,
    started_at: timestamp,
    updated_at: timestamp,
    error: null,
    trace: [
      {
        id: "search-1",
        tool: "web_search",
        status: "succeeded",
        started_at: timestamp,
        finished_at: timestamp,
        input: { query: "smart device releases" },
        output: { provider: "AgentCore Web Search" },
      },
    ],
    sources: [
      {
        id: "S1",
        url: "https://example.com/releases",
        title: "Device releases",
        published_at: "2026-09-09",
        retrieved_at: timestamp,
        read: true,
      },
    ],
    artifacts: [{ name: "results.csv", bytes: 21, sha256: "a".repeat(64) }],
    has_previous_delivery: false,
    validation: null,
  };
  const task = {
    id: "evidence-task",
    title: "Verified device research",
    spec: "Collect current releases with sources.",
    category: "Research",
    budget: "0.05",
    status: "executing",
    is_demo: true,
    deadline: timestamp,
    created_at: timestamp,
    winner_id: "demo-scout",
    bids: [],
    delivery: null,
    rating: null,
    payment: null,
    auto_execute: true,
    automation: {
      status: "queued",
      stage: "executing",
      attempts: 0,
      error: null,
    },
    execution,
  };
  let reads = 0;
  const writes: string[] = [];
  await page.route("**/api/tasks**", async (route) => {
    const request = route.request();
    if (request.method() !== "GET") writes.push(request.method());
    const path = new URL(request.url()).pathname;
    if (path.endsWith("/results.csv"))
      return route.fulfill({
        json: { name: "results.csv", content: "device,source\nA,S1\n" },
      });
    if (path.endsWith("/evidence-task")) {
      reads++;
      return route.fulfill({
        json:
          reads < 2
            ? task
            : {
                ...task,
                status: "completed",
                delivery:
                  "# Verified findings\n\nA sourced device report. [S1]",
                automation: {
                  ...task.automation,
                  status: "completed",
                  stage: "completed",
                },
                execution: {
                  ...execution,
                  status: "completed",
                  validation: {
                    passed: true,
                    reason: "Evidence supports the result.",
                    checks: [
                      {
                        requirement: "Read current sources",
                        passed: true,
                        evidence: "The source page was read.",
                      },
                    ],
                  },
                },
              },
      });
    }
    return route.fulfill({ json: [task] });
  });
  await page.goto("/#tasks");
  await page.getByRole("button", { name: /Verified device research/ }).click();
  const panel = page.getByRole("region", { name: "Execution evidence" });
  await expect(
    panel.getByText("AgentCore Web Search", { exact: true }),
  ).toBeVisible();
  await expect(
    panel.getByRole("link", { name: /Device releases/ }),
  ).toHaveAttribute("href", "https://example.com/releases");
  await expect(
    panel.getByText(/Page read · Published: 2026-09-09/),
  ).toBeVisible();
  await expect(
    panel.getByText("Tools ran and the result passed evidence checks."),
  ).toBeVisible({ timeout: 15000 });
  const download = page.waitForEvent("download");
  await panel.getByRole("button", { name: /results.csv/ }).click();
  expect((await download).suggestedFilename()).toBe("results.csv");
  await panel.getByText("Acceptance checks · Passed").click();
  await expect(panel.getByText("The source page was read.")).toBeVisible();
  expect(writes).toEqual([]);
});
