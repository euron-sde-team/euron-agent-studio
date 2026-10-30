/**
 * README screenshots (1440x900 at 2x) and tour frames, from the seeded demo workspace.
 * Every image shows the real stack: nothing here is mocked.
 */
import { mkdirSync, rmSync } from "node:fs";
import path from "node:path";

import { expect, test, type Page } from "@playwright/test";

import { WORKSPACE, apiGet, flowId, settle, signIn } from "../helpers";

const SHOTS = path.resolve(__dirname, "../../docs/assets/screenshots");
const FRAMES = path.resolve(__dirname, "../.capture/frames");
rmSync(FRAMES, { recursive: true, force: true });
mkdirSync(SHOTS, { recursive: true });
mkdirSync(FRAMES, { recursive: true });

type Item = { id: string; flow_name?: string; status?: string };

let frame = 0;
async function shot(page: Page, name: string): Promise<void> {
  await settle(page);
  // A clicked tab or button keeps a focus ring; screenshots show the page at rest.
  await page.evaluate(() => (document.activeElement as HTMLElement | null)?.blur());
  await page.screenshot({ path: path.join(SHOTS, `${name}.png`) });
}
async function tourFrame(page: Page, holdMs = 1600): Promise<void> {
  frame += 1;
  const file = path.join(FRAMES, `${String(frame).padStart(3, "0")}-${holdMs}.png`);
  await page.screenshot({ path: file, scale: "css" });
}

/** Fit the whole graph into the canvas after a panel changed its size. */
async function fit(page: Page): Promise<void> {
  await page.locator(".react-flow__controls-fitview").click();
  await page.waitForTimeout(500);
}

test.describe.configure({ mode: "serial" });
// Captures run on a busy laptop as often as on CI: allow slow pages rather than flake.
test.setTimeout(300_000);

test("sign-in page", async ({ page }) => {
  await page.goto("/login");
  await settle(page);
  await page.screenshot({ path: path.join(SHOTS, "01-sign-in.png") });
  await tourFrame(page, 1400);
});

test("dashboard, flows, the editor, a live run and the Python export", async ({ page }) => {
  await signIn(page, "owner");
  const base = `/w/${WORKSPACE}`;

  await page.goto(`${base}/dashboard`);
  await expect(page.getByText("Success rate")).toBeVisible();
  await page.waitForTimeout(900); // the volume chart animates in
  await shot(page, "02-dashboard");
  await tourFrame(page, 2400);

  await page.goto(`${base}/flows`);
  await expect(page.getByTestId("flow-link").first()).toBeVisible();
  await shot(page, "03-flows");
  await tourFrame(page, 2000);

  // The triage flow: classify, look up and search in parallel, draft, then a human review.
  await page.goto(`${base}/flows/${await flowId(page, "Support ticket triage")}`);
  await expect(page.getByTestId("canvas")).toBeVisible();
  await page.waitForTimeout(700);
  await shot(page, "04-editor");
  await tourFrame(page, 2600);

  // The lead flow's agent with the two tools wired to it.
  await page.goto(`${base}/flows/${await flowId(page, "Inbound lead qualification")}`);
  await expect(page.getByTestId("canvas")).toBeVisible();
  await page.getByRole("button", { name: "Hide nodes" }).click();
  await page.getByTestId("node-outreach").click();
  await expect(page.getByTestId("inspector")).toBeVisible();
  await fit(page);
  await shot(page, "05-editor-agent");
  await tourFrame(page, 2400);

  // Run it: the trace streams in under the canvas; the agent's tool calls in the inspector.
  await page.getByTestId("run-flow").click();
  await page.getByTestId("start-run").click();
  const panel = page.getByTestId("run-panel");
  await expect(panel.getByText("Succeeded")).toBeVisible({ timeout: 60_000 });
  await panel.getByRole("button", { name: /Outreach agent/ }).click();
  await page.getByTestId("inspector-run-tab").click();
  await fit(page);
  await shot(page, "06-live-run");
  await tourFrame(page, 3000);
  await page.getByRole("button", { name: "Show nodes" }).click();

  await page.getByTestId("export-python").click();
  const dialog = page.getByRole("dialog", { name: "Export to Python" });
  await expect(dialog.getByLabel("Python script")).toContainText("def run_flow(");
  await page.waitForTimeout(400);
  await shot(page, "07-export-python");
  await tourFrame(page, 2600);
  await page.keyboard.press("Escape");
});

test("runs, the run inspector, approvals, templates, knowledge and settings", async ({ page }) => {
  await signIn(page, "owner");
  const base = `/w/${WORKSPACE}`;

  await page.goto(`${base}/runs`);
  await expect(page.getByTestId("run-link").first()).toBeVisible();
  await shot(page, "08-runs");
  await tourFrame(page, 2000);

  // A research brief run: the loop fans out, the timeline shows each question in parallel.
  const runs = await apiGet<{ items: Item[] }>(page, "/runs?status=succeeded&limit=60");
  const research = runs.items.find((r) => r.flow_name === "Research brief")!;
  await page.goto(`${base}/runs/${research.id}`);
  await expect(page.getByTestId("timeline")).toBeVisible();
  // Pick the step on the graph, so the page stays at the top: header, totals, graph, timeline.
  await page.getByTestId("node-compose").click();
  await expect(page.getByText("Write the brief").first()).toBeVisible();
  await page.waitForTimeout(600);
  await shot(page, "09-run-inspector");
  await tourFrame(page, 2800);

  // A failed invoice run: where it failed and why.
  const failed = await apiGet<{ items: Item[] }>(page, "/runs?status=failed&limit=5");
  await page.goto(`${base}/runs/${failed.items.at(-1)!.id}`);
  await expect(page.getByTestId("timeline")).toBeVisible();
  await page.waitForTimeout(600);
  await shot(page, "10-run-failed");
  await tourFrame(page, 2000);

  await page.goto(`${base}/approvals`);
  await expect(page.getByTestId("approve").first()).toBeVisible();
  await shot(page, "11-approvals");
  await tourFrame(page, 2400);

  await page.goto(`${base}/templates`);
  await expect(page.getByTestId("gallery-support-triage")).toBeVisible();
  await page.waitForTimeout(800);
  await shot(page, "12-templates");
  await tourFrame(page, 2000);

  const kbs = await apiGet<{ items: { id: string; name: string }[] }>(page, "/knowledge-bases");
  const handbook = kbs.items.find((kb) => kb.name === "Employee handbook") ?? kbs.items[0]!;
  await page.goto(`${base}/knowledge/${handbook.id}`);
  await page.getByLabel("Search query").fill("How many unused vacation days carry over?");
  await page.getByRole("button", { name: "Search", exact: true }).click();
  await expect(page.getByTestId("search-results")).toBeVisible();
  await shot(page, "13-knowledge");
  await tourFrame(page, 2200);

  await page.goto(`${base}/flows/${await flowId(page, "Support ticket triage")}`);
  await page.getByRole("button", { name: "More actions" }).click();
  await page.getByRole("menuitem", { name: /Triggers/ }).click();
  await expect(page.getByRole("dialog", { name: "Triggers" })).toBeVisible();
  await page
    .getByRole("dialog")
    .getByRole("tab", { name: /Webhook/ })
    .click();
  await page.waitForTimeout(400);
  await shot(page, "14-triggers");
  await page.keyboard.press("Escape");

  await page.goto(`${base}/settings`);
  await page.getByRole("tab", { name: "Activity" }).click();
  await expect(page.getByText(/published/).first()).toBeVisible();
  await shot(page, "15-activity");
  await tourFrame(page, 1800);
});

test("the editor in the dark theme", async ({ browser }) => {
  const context = await browser.newContext({
    viewport: { width: 1440, height: 900 },
    deviceScaleFactor: 2,
    colorScheme: "dark",
  });
  const page = await context.newPage();
  await signIn(page, "owner");
  // A compact flow: an agent with two tools, its settings open next to it.
  await page.goto(`/w/${WORKSPACE}/flows/${await flowId(page, "HR policy assistant")}`);
  await expect(page.getByTestId("canvas")).toBeVisible();
  await page.getByRole("button", { name: "Hide nodes" }).click();
  await page.getByTestId("node-answer").click();
  await expect(page.getByTestId("inspector")).toBeVisible();
  await fit(page);
  await shot(page, "16-editor-dark");
  await tourFrame(page, 2200);
  await context.close();
});
