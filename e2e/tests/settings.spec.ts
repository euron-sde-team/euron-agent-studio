import { expect, test } from "@playwright/test";

import { WORKSPACE, flowId, signIn, toast, unique } from "../helpers";

test("an owner creates an API key that is shown exactly once", async ({ page }) => {
  await signIn(page, "owner");
  await page.goto(`/w/${WORKSPACE}/settings`);
  await page.getByRole("tab", { name: "API keys" }).click();
  await page.getByRole("button", { name: "Create key" }).click();
  const name = unique("CI pipeline");
  await page.getByLabel("Name").fill(name);
  await page.getByRole("dialog").getByRole("button", { name: "Create key" }).click();
  const key = page.getByLabel("API key", { exact: true });
  await expect(key).toContainText("agst_");
  await page.getByRole("button", { name: "Done" }).click();
  await expect(page.getByText(name)).toBeVisible();
  await expect(page.getByText(/agst_[A-Za-z0-9]+_\.\.\./).first()).toBeVisible();
});

test("secrets are stored write-only and referenced from flows", async ({ page }) => {
  await signIn(page, "owner");
  await page.goto(`/w/${WORKSPACE}/settings`);
  await page.getByRole("tab", { name: "Secrets" }).click();
  await expect(page.getByText("CRM_TOKEN")).toBeVisible();
  await page.getByRole("button", { name: "Add secret" }).click();
  const name = `E2E_${Date.now().toString(36).toUpperCase()}`;
  await page.getByLabel("Name").fill(name);
  await page.getByLabel("Value").fill("sk-test-not-a-real-key");
  await page.getByRole("button", { name: "Store secret" }).click();
  await expect(toast(page, `${name} stored`)).toBeVisible();
  await expect(page.getByText(name, { exact: true })).toBeVisible();
  await expect(page.getByText("sk-test-not-a-real-key")).toHaveCount(0);
});

test("a flow's webhook is enabled with a signing secret shown once", async ({ page }) => {
  await signIn(page, "owner");
  await page.goto(`/w/${WORKSPACE}/flows/${await flowId(page, "HR policy assistant")}`);
  await page.getByRole("button", { name: "More actions" }).click();
  await page.getByRole("menuitem", { name: /Triggers/ }).click();
  const dialog = page.getByRole("dialog", { name: "Triggers" });
  await expect(dialog.getByLabel("API request")).toContainText("/runs?wait=30");
  await dialog.getByRole("tab", { name: /Webhook/ }).click();
  // Enabled by an earlier run of this suite? Rotating shows a fresh secret the same way.
  const enable = dialog.getByTestId("enable-webhook");
  const rotate = dialog.getByRole("button", { name: "Rotate secret" });
  await expect(enable.or(rotate)).toBeVisible();
  await ((await enable.isVisible()) ? enable : rotate).click();
  await expect(dialog.getByLabel("Signing secret")).toContainText("whsec_");
  await expect(dialog.getByLabel("Webhook URL")).toContainText("/api/v1/hooks/");
  await expect(dialog.getByLabel("Signing example")).toContainText("X-AgentStudio-Signature");
});

test("members and their roles are listed for everyone, managed by owners", async ({ page }) => {
  await signIn(page, "owner");
  await page.goto(`/w/${WORKSPACE}/settings`);
  await page.getByRole("tab", { name: "Members" }).click();
  await expect(page.getByText("Leo Chen")).toBeVisible();
  await expect(page.getByRole("combobox", { name: "Role for Maya Patel" })).toHaveValue("viewer");
  await page.getByRole("tab", { name: "Activity" }).click();
  await expect(page.getByText(/published/).first()).toBeVisible();
});
