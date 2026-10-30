import { expect, test } from "@playwright/test";

import { WORKSPACE, signIn } from "../helpers";

test("a template becomes a flow that runs with its sample", async ({ page }) => {
  await signIn(page, "editor");
  await page.goto(`/w/${WORKSPACE}/templates`);
  await expect(page.getByTestId("gallery-policy-assistant")).toBeVisible();
  await page.getByTestId("use-policy-assistant").click();
  await expect(page.getByTestId("flow-name")).toHaveText("HR policy assistant");
  await expect(page.getByTestId("node-answer")).toBeVisible();

  // The sample prefills the run dialog: one click to see the agent at work.
  await page.getByTestId("run-flow").click();
  await expect(page.getByLabel("question", { exact: true })).not.toHaveValue("");
  await page.getByTestId("start-run").click();
  const panel = page.getByTestId("run-panel");
  await expect(panel.getByText("Succeeded")).toBeVisible({ timeout: 45_000 });
  await expect(panel.locator("pre")).toContainText("25 days of paid vacation");
});

test("the dashboard summarises two weeks of runs", async ({ page }) => {
  await signIn(page, "owner");
  await page.goto(`/w/${WORKSPACE}/dashboard`);
  await expect(page.getByText("Success rate")).toBeVisible();
  await expect(page.getByText("Runs per day")).toBeVisible();
  await expect(page.getByText("Busiest flows")).toBeVisible();
  await page.getByRole("link", { name: /Waiting for approval/ }).click();
  await expect(page).toHaveURL(new RegExp(`/w/${WORKSPACE}/approvals`));
});
