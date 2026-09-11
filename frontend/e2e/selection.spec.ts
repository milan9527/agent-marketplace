import { expect, test } from "@playwright/test";
import type { Task } from "../src/types";

for (const mode of ["auto", "manual"] as const) {
  test(`${mode} task selection chooses an eligible agent and waits for payment`, async ({
    page,
  }, info) => {
    const paymentRequests: string[] = [];
    page.on("request", (request) => {
      if (request.url().endsWith("/pay")) paymentRequests.push(request.url());
    });
    await page.goto("/");
    await page
      .getByRole("button", { name: "Post a task", exact: true })
      .click();
    const title = `${mode} selection ${info.project.name} ${Date.now()}`;
    await page.getByLabel("Task title").fill(title);
    await page
      .getByLabel("Your brief")
      .fill(
        "Research developer tool positioning, compare the supplied criteria, and explain the recommendation.",
      );
    await page
      .getByRole("combobox", { name: "Agent selection", exact: true })
      .selectOption(mode);
    await page
      .getByRole("combobox", { name: "Agent pool", exact: true })
      .selectOption("live");
    await page.getByRole("button", { name: "Post task & get bids" }).click();
    const dialog = page.getByRole("dialog");
    if (mode === "manual") {
      await expect(
        dialog.getByText("8 specialists. Your choice."),
      ).toBeVisible();
      await dialog
        .getByRole("button", { name: "Choose best agent", exact: true })
        .click();
    }
    await expect(
      dialog.getByText("Automatic selection", { exact: true }),
    ).toBeVisible();
    await expect(
      dialog.getByText(/Automatically selected .*highest quality/),
    ).toBeVisible();
    await expect(
      dialog.getByRole("button", { name: /Pay \$.* & authorize/ }),
    ).toBeVisible();
    await expect(
      dialog.getByRole("button", { name: "Get deliverable" }),
    ).toHaveCount(0);
    expect(paymentRequests).toEqual([]);
    const tasks: Task[] = await (await page.request.get("/api/tasks")).json();
    const selected = tasks.find((task) => task.title === title)!;
    expect(selected.status).toBe("awaiting_payment");
    expect(selected.payment).toBeNull();
    expect(selected.selection_mode).toBe("auto");
    const winner = selected.bids.find(
      (bid) => bid.agent.id === selected.winner_id,
    )!;
    expect(winner.match_score).toBeGreaterThanOrEqual(70);
    expect(winner.within_budget).toBe(true);
    await page.screenshot({
      path: `test-results/selection-${mode}-${info.project.name}.png`,
      fullPage: true,
      animations: "disabled",
    });
    await page.getByRole("button", { name: "Close dialog" }).click();
    await page.reload();
    await page.getByRole("button", { name: new RegExp(title) }).click();
    await expect(
      page
        .getByRole("dialog")
        .getByText(/Automatically selected .*highest quality/),
    ).toBeVisible();
  });
}
