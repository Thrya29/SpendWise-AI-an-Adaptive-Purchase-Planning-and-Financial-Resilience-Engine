import { expect, test, type Page } from "@playwright/test";
import path from "node:path";

const STATEMENT = path.resolve(__dirname, "../../backend/tests/fixtures/statements/sbi_style.txt");

/**
 * Fail on JavaScript errors, CSP violations, server errors and unexpected 4xx responses.
 * The one expected 4xx: on first load an anonymous visitor has no session to refresh.
 */
function watch(page: Page): string[] {
  const problems: string[] = [];
  page.on("console", (msg) => {
    // Failed requests are judged by their responses below, where the URL is known.
    if (msg.type() === "error" && !msg.text().startsWith("Failed to load resource")) {
      problems.push(msg.text());
    }
  });
  page.on("pageerror", (err) => problems.push(err.message));
  page.on("response", (res) => {
    const expected = res.status() === 401 && res.url().endsWith("/api/v1/auth/refresh");
    if (res.status() >= 400 && !expected) problems.push(`${res.status()} ${res.url()}`);
  });
  return problems;
}

test("a new user imports a statement and runs the planner on a phone", async ({ page }) => {
  const problems = watch(page);
  const email = `e2e-${Date.now()}@example.com`;

  await page.goto("/register");
  await page.getByLabel("Name").fill("E2E Tester");
  await page.getByLabel("Email").fill(email);
  await page.getByLabel("Password", { exact: true }).fill("correct-horse-battery");
  await page.getByLabel("Confirm password").fill("correct-horse-battery");
  await page.getByLabel("City").fill("Bengaluru");
  await page.getByRole("button", { name: "Create account" }).click();
  await expect(page).toHaveURL(/\/dashboard/);

  // No horizontal scrolling at phone width.
  const overflow = await page.evaluate(
    () => document.documentElement.scrollWidth - document.documentElement.clientWidth,
  );
  expect(overflow).toBeLessThanOrEqual(1);
  await page.screenshot({ path: "test-results/screens/dashboard-new.png", fullPage: true });

  await page.goto("/import");
  await page.getByLabel("Statement file").setInputFiles(STATEMENT);
  await page.getByRole("button", { name: "Read statement" }).click();
  await expect(page.getByText("All 79 rows match the running balance")).toBeVisible();
  await expect(page.getByLabel("Set up Salary")).toBeChecked();
  await page.screenshot({ path: "test-results/screens/import-preview.png", fullPage: true });
  await page.getByRole("button", { name: /^Import \d+ items?$/ }).click();
  await expect(page.getByText("Imported", { exact: true })).toBeVisible();

  await page.goto("/plan");
  await expect(page.getByRole("heading", { name: /needs, wants/i })).toBeVisible();

  await page.goto("/planner");
  await page.getByRole("button", { name: "Run planner" }).first().click();
  await expect(page.getByText(/Optimal|Best found/)).toBeVisible();
  await page.screenshot({ path: "test-results/screens/planner.png", fullPage: true });

  await page.goto("/alerts");
  await expect(page.getByRole("heading", { name: "Alerts" })).toBeVisible();
  await page.goto("/settings");
  await expect(page.getByText("Help improve SpendWise")).toBeVisible();

  const manifest = await page.request.get("/manifest.webmanifest");
  expect(manifest.ok()).toBe(true);
  const csp = (await page.request.get("/login")).headers()["content-security-policy"];
  expect(csp).toContain("frame-ancestors 'none'");

  expect(problems, problems.join("\n")).toEqual([]);
});
