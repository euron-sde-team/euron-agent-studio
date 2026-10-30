import { expect, test } from "@playwright/test";

import { WORKSPACE, signIn, unique } from "../helpers";

const NOTE = `# Office move

## New address
From 3 November the Northwind office is at 18 Harbour Street, Floor 4.

## Parking
Visitor parking is in the Harbour Street garage; ask reception for a validation ticket.
`;

test("upload a document and search it the way a flow does", async ({ page }) => {
  await signIn(page, "editor");
  await page.goto(`/w/${WORKSPACE}/knowledge`);
  await page.getByTestId("new-kb").click();
  const name = unique("Facilities");
  await page.getByLabel("Name").fill(name);
  await page.getByRole("button", { name: "Create" }).click();
  await expect(page.getByRole("heading", { name })).toBeVisible();

  await page.getByLabel("Documents to upload").setInputFiles({
    name: "office-move.md",
    mimeType: "text/markdown",
    buffer: Buffer.from(NOTE),
  });
  await expect(page.getByTestId("documents")).toContainText("Office move", { timeout: 45_000 });
  await expect(page.getByTestId("documents")).toContainText("2 passages");

  await page.getByLabel("Search query").fill("Where do visitors park?");
  await page.getByRole("button", { name: "Search", exact: true }).click();
  const results = page.getByTestId("search-results");
  await expect(results).toContainText("Parking");
  await expect(results.locator("mark").first()).toBeVisible();

  await page.getByRole("button", { name: "Delete office-move.md" }).click();
  await expect(page.getByText("No documents yet")).toBeVisible();
});
