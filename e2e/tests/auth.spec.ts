import { expect, test } from "@playwright/test";

import { WORKSPACE, flowId, signIn, signInWithForm } from "../helpers";

test("an owner signs in, lands on the dashboard and signs out", async ({ page }) => {
  await signInWithForm(page, "owner");
  await expect(page.getByRole("heading", { name: "Dashboard" })).toBeVisible();
  await expect(page.getByText("Offline model (deterministic)")).toBeVisible();
  await page.getByRole("button", { name: "Account menu" }).click();
  await page.getByRole("menuitem", { name: "Sign out" }).click();
  await expect(page).toHaveURL(/\/login/);
});

test("a wrong password is refused with a clear message", async ({ page }) => {
  await page.goto("/login");
  await page.getByLabel("Email").fill("nobody@northwind.example");
  await page.getByLabel("Password").fill("not-the-password");
  await page.getByRole("button", { name: "Sign in" }).click();
  await expect(page.getByRole("alert").filter({ hasText: "incorrect" })).toHaveText(
    "Email or password is incorrect.",
  );
});

test("workspace pages send signed-out visitors to sign in and back", async ({ page }) => {
  await page.goto(`/w/${WORKSPACE}/runs`);
  await expect(page).toHaveURL(/\/login\?next=/);
});

test("viewers can open flows but not change or run them", async ({ page }) => {
  await signIn(page, "viewer");
  await page.goto(`/w/${WORKSPACE}/flows/${await flowId(page, "Support ticket triage")}`);
  await expect(page.getByTestId("canvas")).toBeVisible();
  await expect(page.getByText("View only")).toBeVisible();
  await expect(page.getByTestId("run-flow")).toHaveCount(0);
  await expect(page.getByTestId("publish")).toHaveCount(0);
  await expect(page.getByRole("complementary", { name: "Nodes" })).toHaveCount(0);
  // Export stays available: reading a flow includes taking it as Python.
  await expect(page.getByTestId("export-python")).toBeVisible();
});
