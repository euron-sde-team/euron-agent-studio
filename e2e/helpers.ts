import { existsSync, mkdirSync, readFileSync, writeFileSync } from "node:fs";
import path from "node:path";

import { expect, type Page } from "@playwright/test";

export const API_URL = process.env.API_URL ?? "http://localhost:8120";
export const PASSWORD = process.env.DEMO_PASSWORD ?? "";
export const WORKSPACE = "northwind-operations";

export const PEOPLE = {
  owner: { email: "ava.martin@northwind.example", name: "Ava Martin" },
  editor: { email: "leo.chen@northwind.example", name: "Leo Chen" },
  viewer: { email: "maya.patel@northwind.example", name: "Maya Patel" },
} as const;

export function requirePassword(): string {
  if (!PASSWORD) throw new Error("Set DEMO_PASSWORD (make e2e reads it from deploy/compose/.env)");
  return PASSWORD;
}

const SESSIONS = path.resolve(__dirname, ".auth");

/** Sign in through the form, exactly as a person does. */
export async function signInWithForm(
  page: Page,
  who: keyof typeof PEOPLE = "owner",
): Promise<void> {
  await page.goto("/login");
  await page.getByLabel("Email").fill(PEOPLE[who].email);
  await page.getByLabel("Password").fill(requirePassword());
  await page.getByRole("button", { name: "Sign in" }).click();
  await expect(page).toHaveURL(/\/w\/[^/]+\/dashboard/);
}

/**
 * A signed-in page for one demo person. The session cookie from the first form sign-in is
 * reused by later tests: the API allows ten sign-ins a minute per address, and the suites
 * would otherwise trip that limit themselves. A stale cookie (after `make down`) falls back
 * to the form.
 */
export async function signIn(page: Page, who: keyof typeof PEOPLE = "owner"): Promise<void> {
  const saved = path.join(SESSIONS, `${who}.json`);
  if (existsSync(saved)) {
    await page.context().addCookies(JSON.parse(readFileSync(saved, "utf8")));
    await page.goto("/");
    await page.waitForURL(/\/(w\/[^/]+\/dashboard|login)/);
    if (!page.url().includes("/login")) return;
    await page.context().clearCookies();
  }
  await signInWithForm(page, who);
  mkdirSync(SESSIONS, { recursive: true });
  writeFileSync(saved, JSON.stringify(await page.context().cookies()));
}

/** Wait until the page has settled: no pending network, fonts ready, transitions finished. */
export async function settle(page: Page): Promise<void> {
  await page.waitForLoadState("networkidle");
  await page.evaluate(async () => {
    await document.fonts.ready;
    // Spinners and pulsing dots repeat forever; only wait for animations that end.
    const finite = document
      .getAnimations()
      .filter((animation) => animation.effect?.getTiming().iterations !== Infinity);
    await Promise.all(finite.map((animation) => animation.finished.catch(() => undefined)));
  });
}

/** A toast notification with the given text (sonner renders them as list items). */
export function toast(page: Page, text: string | RegExp) {
  return page.locator("[data-sonner-toast]").filter({ hasText: text });
}

/** GET a workspace API path with the page's session cookie. */
export async function apiGet<T>(page: Page, apiPath: string): Promise<T> {
  const response = await page.request.get(`${API_URL}/api/v1/workspaces/${WORKSPACE}${apiPath}`);
  expect(response.ok(), apiPath).toBeTruthy();
  return (await response.json()) as T;
}

type Named = { id: string; name: string };

/** The id of the demo flow whose name contains `search`. */
export async function flowId(page: Page, search: string): Promise<string> {
  const found = await apiGet<{ items: Named[] }>(page, `/flows?q=${encodeURIComponent(search)}`);
  expect(found.items.length, search).toBeGreaterThan(0);
  return found.items[0]!.id;
}

/** A unique, readable suffix so repeated runs against one database never collide. */
export function unique(prefix: string): string {
  return `${prefix} ${Date.now().toString(36).slice(-5)}`;
}
