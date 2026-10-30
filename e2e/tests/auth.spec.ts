import { expect, test } from "@playwright/test";

import { WORKSPACE, flowId, signIn, signInWithForm, toast, unique } from "../helpers";

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

test("a new member signs in with the temporary password and replaces it", async ({
  page,
  browser,
}) => {
  // Leo owns his own workspace; adding people there keeps the Northwind demo data tidy.
  const email = `${unique("new.member").replace(" ", ".")}@northwind.example`;
  await signIn(page, "editor");
  await page.goto("/w/leo-s-experiments/settings");
  await page.getByRole("tab", { name: "Members" }).click();
  await page.getByRole("button", { name: "Add member" }).click();
  const dialog = page.getByRole("dialog");
  await dialog.getByLabel("Email").fill(email);
  await dialog.getByRole("button", { name: "Add member" }).click();
  const temporary = (await dialog.getByLabel("Temporary password").textContent())?.trim() ?? "";
  expect(temporary.length).toBeGreaterThanOrEqual(10);

  // The new member, in their own browser.
  const context = await browser.newContext();
  const member = await context.newPage();
  await member.goto("/login");
  await member.getByLabel("Email").fill(email);
  await member.getByLabel("Password").fill(temporary);
  await member.getByRole("button", { name: "Sign in" }).click();
  await expect(member).toHaveURL(/\/w\/leo-s-experiments\/dashboard/);

  const replacement = `${temporary}-mine`;
  await member.getByRole("button", { name: "Account menu" }).click();
  await member.getByRole("menuitem", { name: "Change password" }).click();
  await member.getByLabel("Current password").fill(temporary);
  await member.getByLabel("New password", { exact: true }).fill(replacement);
  await member.getByLabel("Confirm the new password").fill(replacement);
  await member.getByRole("button", { name: "Change password" }).click();
  await expect(toast(member, "Password changed")).toBeVisible();

  await member.getByRole("button", { name: "Account menu" }).click();
  await member.getByRole("menuitem", { name: "Sign out" }).click();
  await member.getByLabel("Email").fill(email);
  await member.getByLabel("Password").fill(replacement);
  await member.getByRole("button", { name: "Sign in" }).click();
  await expect(member).toHaveURL(/\/w\/leo-s-experiments\/dashboard/);
  await context.close();
});
