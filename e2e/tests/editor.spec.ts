import { expect, test, type Page } from "@playwright/test";

import { WORKSPACE, settle, signIn, unique } from "../helpers";

async function newBlankFlow(page: Page, name: string): Promise<void> {
  await page.goto(`/w/${WORKSPACE}/flows`);
  await page.getByTestId("new-flow").click();
  await page.getByRole("tab", { name: "Blank" }).click();
  await page.getByLabel("Name").fill(name);
  await page.getByTestId("create-flow").click();
  await expect(page.getByTestId("flow-name")).toHaveText(name);
  await expect(page.getByTestId("node-start")).toBeVisible();
}

async function saved(page: Page): Promise<void> {
  await expect(page.getByTestId("save-state")).toHaveText(/Saved/, { timeout: 15_000 });
}

test.describe.configure({ mode: "serial" });

test("build a flow on the canvas, wire it, run it and read the trace", async ({ page }) => {
  await signIn(page, "editor");
  await newBlankFlow(page, unique("Summarise a note"));

  // Select Start, then add a Prompt from the palette: it lands to the right, wired in.
  await page.getByTestId("node-start").click();
  await page.getByTestId("palette-llm").click();
  const prompt = page.getByTestId("node-prompt");
  await expect(prompt).toBeVisible();
  await expect(page.getByTestId("inspector")).toBeVisible();

  // Type a prompt; "{{" offers everything this node can read.
  const promptField = page.getByRole("textbox", { name: "Prompt", exact: true });
  await promptField.fill("Summarize this note in one sentence: {{inp");
  await page.getByRole("listbox", { name: "References" }).getByText("inputs.input").click();
  await expect(promptField).toHaveValue("Summarize this note in one sentence: {{inputs.input}}");

  // Wire the prompt into the output, then point the output at the prompt's text.
  await page.getByRole("button", { name: "Close settings" }).click();
  await page.locator(".react-flow__controls-fitview").click();
  await page.waitForTimeout(400);
  await prompt.locator(".react-flow__handle-right").dragTo(
    page.getByTestId("node-result").locator(".react-flow__handle-left"),
  );
  await page.getByTestId("node-result").click();
  const value = page.getByRole("textbox", { name: "Value" }).first();
  await value.fill("{{prompt.text}}");
  await saved(page);
  await expect(page.getByTestId("issues-button")).toHaveText(/Valid/);

  await page.getByTestId("run-flow").click();
  await page
    .getByLabel("input", { exact: true })
    .fill(
      "The vendor review is moved to Thursday at 10:00. Bring the Q3 invoices and the delivery log.",
    );
  await page.getByTestId("start-run").click();
  const panel = page.getByTestId("run-panel");
  await expect(panel.getByText("Succeeded")).toBeVisible({ timeout: 30_000 });
  await expect(panel.getByText("Outputs")).toBeVisible();
  await expect(panel.locator("pre")).toContainText('"result"');
  // Every step's trace is one click away.
  await panel.getByRole("button", { name: /Prompt/ }).click();
  await page.getByTestId("inspector-run-tab").click();
  await expect(page.getByTestId("inspector")).toContainText("Tokens");
});

test("undo, redo and tidy-up work on the canvas", async ({ page }) => {
  await signIn(page, "editor");
  await newBlankFlow(page, unique("Undo check"));
  await page.getByTestId("node-start").click();
  await page.getByTestId("palette-calculator").click();
  await expect(page.getByTestId("node-calculate")).toBeVisible();
  await saved(page);

  await page.getByTestId("node-calculate").click();
  await page.getByRole("button", { name: "Delete node" }).click();
  await expect(page.getByTestId("node-calculate")).toHaveCount(0);
  await page.getByRole("button", { name: "Undo", exact: true }).click();
  await expect(page.getByTestId("node-calculate")).toBeVisible();
  await page.getByRole("button", { name: "Redo", exact: true }).click();
  await expect(page.getByTestId("node-calculate")).toHaveCount(0);
  await page.keyboard.press("ControlOrMeta+z");
  await expect(page.getByTestId("node-calculate")).toBeVisible();

  const before = await page.getByTestId("node-result").boundingBox();
  await page.getByRole("button", { name: "Tidy up", exact: true }).click();
  await page.waitForTimeout(600);
  const after = await page.getByTestId("node-result").boundingBox();
  expect(after).not.toEqual(before);
  await saved(page);
});

test("validation points at the node and the field that need attention", async ({ page }) => {
  await signIn(page, "editor");
  await newBlankFlow(page, unique("Validation check"));
  await page.getByTestId("node-start").click();
  await page.getByTestId("palette-knowledge").click();
  await saved(page);
  await expect(page.getByTestId("issues-button")).toHaveText(/problem/);
  await page.getByTestId("issues-button").click();
  await expect(page.getByTestId("issues-list")).toContainText("Knowledge search");
  // A problem in the list opens the node it belongs to.
  await page.getByTestId("issues-list").getByRole("button").first().click();
  await expect(page.getByTestId("inspector")).toBeVisible();
  await page.keyboard.press("Escape");
  // Choosing a knowledge base and a query clears the problems.
  await page.getByRole("combobox", { name: "Knowledge base" }).selectOption({ index: 1 });
  await page.getByRole("textbox", { name: "Query", exact: true }).fill("{{inputs.input}}");
  await saved(page);
  await settle(page);
  await expect(page.getByTestId("issues-button")).toHaveText(/Valid/);
});

test("drag a node from the palette onto the canvas", async ({ page }) => {
  await signIn(page, "editor");
  await newBlankFlow(page, unique("Drag check"));
  await page.getByTestId("palette-approval").dragTo(page.getByTestId("canvas"), {
    targetPosition: { x: 520, y: 380 },
  });
  await expect(page.getByTestId("node-approval")).toBeVisible();
  await saved(page);
});
