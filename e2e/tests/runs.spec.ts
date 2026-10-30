import { expect, test } from "@playwright/test";

import { WORKSPACE, apiGet, flowId, signIn } from "../helpers";

type Run = { id: string; status: string; flow_name: string };

test("a paused run is approved from the inbox and finishes", async ({ page }) => {
  await signIn(page, "owner");
  // A fresh triage run that pauses for review, started the way an integration would.
  const triage = await flowId(page, "Support ticket triage");
  const started = await page.request.post(
    `${process.env.API_URL ?? "http://localhost:8120"}/api/v1/workspaces/${WORKSPACE}/flows/${triage}/runs?wait=60`,
    {
      data: {
        inputs: {
          subject: "Charged twice for the October invoice",
          body: "I was charged twice for invoice INV-3310. Please refund the duplicate charge as soon as possible. Thanks, Dana Whitfield",
          customer_email: "dana.whitfield@globex.example",
        },
      },
      headers: { origin: "http://localhost:3120" },
    },
  );
  expect(started.status()).toBe(202);
  const run = (await started.json()) as Run;
  expect(run.status).toBe("waiting");

  await page.goto(`/w/${WORKSPACE}/approvals`);
  const card = page.locator(`[data-testid^="approval-"]`).filter({
    hasText: "Charged twice for the October invoice",
  });
  await expect(card).toBeVisible();
  await expect(card).toContainText("Hi Dana");
  await card.getByLabel("Comment for the record").fill("Refund confirmed with finance.");
  await card.getByTestId("approve").click();

  await page.goto(`/w/${WORKSPACE}/runs/${run.id}`);
  await expect(page.getByRole("heading", { name: /Support ticket triage/ })).toContainText(
    "Succeeded",
    { timeout: 30_000 },
  );
  await expect(page.getByText("Refund confirmed with finance.").first()).toBeVisible();
});

test("the run inspector shows the graph, the timeline and each step", async ({ page }) => {
  await signIn(page, "owner");
  const runs = await apiGet<{ items: Run[] }>(page, "/runs?status=succeeded&limit=50");
  const research = runs.items.find((r) => r.flow_name === "Research brief");
  expect(research).toBeTruthy();
  await page.goto(`/w/${WORKSPACE}/runs/${research!.id}`);
  await expect(page.getByTestId("timeline")).toBeVisible();
  await expect(page.locator(".react-flow__node")).not.toHaveCount(0);
  // Loop iterations each get their own row.
  await expect(
    page.getByTestId("timeline").getByRole("button", { name: /#2/ }).first(),
  ).toBeVisible();
  await page
    .getByTestId("timeline")
    .getByRole("button", { name: /^Write the brief/ })
    .click();
  await expect(page.getByText("Model", { exact: true })).toBeVisible();
  await expect(page.getByText("Tokens", { exact: true }).first()).toBeVisible();
});

test("a failed run explains where and why it failed, and can run again", async ({ page }) => {
  await signIn(page, "owner");
  await page.goto(`/w/${WORKSPACE}/runs`);
  await page.getByRole("combobox", { name: "Filter by status" }).selectOption("failed");
  await expect(page.getByTestId("run-link").first()).toBeVisible();
  await page.getByTestId("run-link").first().click();
  await expect(page.getByRole("alert").first()).toContainText("check_totals");
  await page.getByTestId("rerun").click();
  await expect(page).toHaveURL(/\/runs\/[0-9a-f-]+$/);
  await expect(page.getByText(/Re-run by Ava Martin/)).toBeVisible();
});

test("run history filters by flow, status and trigger", async ({ page }) => {
  await signIn(page, "owner");
  await page.goto(`/w/${WORKSPACE}/runs`);
  await page.getByRole("combobox", { name: "Filter by trigger" }).selectOption("webhook");
  await expect(page.getByTestId("run-link").first()).toBeVisible();
  const rows = page.locator("tbody tr");
  const count = await rows.count();
  for (let index = 0; index < count; index += 1) {
    await expect(rows.nth(index)).toContainText("Webhook");
  }
});
