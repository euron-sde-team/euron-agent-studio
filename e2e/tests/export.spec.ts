import { readFileSync } from "node:fs";

import { expect, test } from "@playwright/test";

import { WORKSPACE, flowId, signIn } from "../helpers";

test("export a flow as a standalone Python script", async ({ page }) => {
  await signIn(page, "editor");
  await page.goto(`/w/${WORKSPACE}/flows/${await flowId(page, "Inbound lead qualification")}`);
  await page.getByTestId("export-python").click();
  const dialog = page.getByRole("dialog", { name: "Export to Python" });
  const script = dialog.getByLabel("Python script");
  await expect(script).toContainText("def run_flow(");
  await expect(script).toContainText("import httpx");
  await expect(dialog).toContainText("inbound_lead_qualification.py");

  const download = page.waitForEvent("download");
  await dialog.getByTestId("download-python").click();
  const file = await download;
  expect(file.suggestedFilename()).toBe("inbound_lead_qualification.py");
  const source = readFileSync((await file.path())!, "utf8");
  expect(source.startsWith("#!/usr/bin/env python3")).toBe(true);
  expect(source).toContain("pip install httpx jmespath");
});

test("export and import a flow as JSON", async ({ page }) => {
  await signIn(page, "editor");
  await page.goto(`/w/${WORKSPACE}/flows/${await flowId(page, "Meeting notes to tasks")}`);
  await page.getByRole("button", { name: "More actions" }).click();
  const download = page.waitForEvent("download");
  await page.getByRole("menuitem", { name: "Export JSON" }).click();
  const file = await download;
  expect(file.suggestedFilename()).toBe("meeting-notes-to-tasks.json");
  const path = (await file.path())!;
  const document = JSON.parse(readFileSync(path, "utf8")) as { format: string; name: string };
  expect(document.format).toBe("agentstudio.flow");

  await page.goto(`/w/${WORKSPACE}/flows?new=1`);
  await page.getByRole("tab", { name: "Import" }).click();
  await page.getByLabel("Flow file").setInputFiles(path);
  await expect(page.getByTestId("flow-name")).toHaveText("Meeting notes to tasks");
  await expect(page.getByTestId("node-each_action")).toBeVisible();
});
