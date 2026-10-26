import { expect, test, type Page } from "@playwright/test";
import fs from "node:fs";
import path from "node:path";

/**
 * The extension's popup against the real API, through the web proxy.
 *
 * Browsers don't let automation load unpacked extensions, so the popup's own files are served
 * next to the app and only Chrome's extension APIs (storage, the active tab, reading the page)
 * are replaced. Everything from the popup's request to the saved item is real.
 */
const EXTENSION = path.resolve(__dirname, "../../extension");

const PRODUCT = {
  url: "https://www.amazon.in/dp/B0EXAMPLE1",
  title: "Noise-cancelling headphones",
  price: "24999.00",
  currency: "INR",
  availability: "in_stock",
  source: "structured",
};

async function signUp(page: Page): Promise<void> {
  await page.goto("/register");
  await page.getByLabel("Name").fill("Extension Tester");
  await page.getByLabel("Email").fill(`ext-${Date.now()}@example.com`);
  await page.getByLabel("Password", { exact: true }).fill("correct-horse-battery");
  await page.getByLabel("Confirm password").fill("correct-horse-battery");
  await page.getByLabel("City").fill("Pune");
  await page.getByRole("button", { name: "Create account" }).click();
  await expect(page).toHaveURL(/\/dashboard/);
}

async function openPopup(page: Page, baseURL: string, key: string): Promise<void> {
  await page.route("**/__extension/**", async (route) => {
    const file = path.join(EXTENSION, new URL(route.request().url()).pathname.split("/").pop()!);
    const type = file.endsWith(".js")
      ? "text/javascript"
      : file.endsWith(".css")
        ? "text/css"
        : "text/html";
    await route.fulfill({ body: fs.readFileSync(file), contentType: `${type}; charset=utf-8` });
  });
  await page.addInitScript(
    ({ server, key, product }) => {
      const store: Record<string, string> = { server, key };
      Object.defineProperty(window, "chrome", {
        configurable: true,
        value: {
          storage: {
            local: {
              get: async () => ({ ...store }),
              set: async (v: object) => Object.assign(store, v),
            },
          },
          tabs: { query: async () => [{ id: 1, url: product.url }] },
          scripting: { executeScript: async () => [{ result: product }] },
          permissions: { request: async () => true },
        },
      });
    },
    { server: baseURL, key, product: PRODUCT },
  );
  await page.goto("/__extension/popup.html");
}

test("the popup saves a product through the real API", async ({ page, baseURL }) => {
  await signUp(page);

  await page.goto("/settings");
  await page.getByRole("button", { name: "Create a key" }).click();
  const key = (await page.locator("code", { hasText: "swx_" }).textContent())!.trim();
  expect(key).toMatch(/^swx_/);

  const popup = await page.context().newPage();
  await openPopup(popup, baseURL!, key);
  await expect(popup.getByLabel("Product", { exact: true })).toHaveValue(PRODUCT.title);
  await expect(popup.getByLabel("Price", { exact: true })).toHaveValue("24999.00");
  await expect(popup.getByText("Read from the shop's product data.")).toBeVisible();
  await popup.getByLabel("Type").selectOption("need");
  await popup.getByRole("button", { name: "Save to SpendWise" }).click();
  await expect(popup.getByRole("status")).toContainText("Added “Noise-cancelling headphones”");

  // Saving again offers the same item, matched by its link, and records a lower price.
  await popup.reload();
  await expect(popup.getByLabel("Existing item")).toBeChecked();
  await popup.getByLabel("Price", { exact: true }).fill("22499");
  await popup.getByRole("button", { name: "Save to SpendWise" }).click();
  await expect(popup.getByRole("status")).toContainText("Price drop");
  await popup.close();

  await page.goto("/plan");
  await expect(page.getByText(PRODUCT.title)).toBeVisible();
  await expect(page.getByText(/22,499/).first()).toBeVisible();
});
