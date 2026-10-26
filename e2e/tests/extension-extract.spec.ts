import { expect, test, type Page } from "@playwright/test";
import fs from "node:fs";
import path from "node:path";

/**
 * The browser extension's price reader, run in a real browser against small sample pages.
 * The samples mimic how each kind of site marks up prices; they are not copies of real pages.
 */
const EXTENSION = path.resolve(__dirname, "../../extension");
const extractSource = fs.readFileSync(path.join(EXTENSION, "extract.js"), "utf8");
const commonSource = fs.readFileSync(path.join(EXTENSION, "common.js"), "utf8");

type Found = {
  url: string;
  title: string;
  price: string | null;
  currency: string | null;
  availability: string;
  source: string;
};

async function read(page: Page, html: string, url = "https://shop.example/p/1"): Promise<Found> {
  await page.route(url, (route) =>
    route.fulfill({ contentType: "text/html; charset=utf-8", body: html }),
  );
  await page.goto(url);
  await page.addScriptTag({ content: extractSource });
  return page.evaluate(() =>
    (window as unknown as { extractProduct: () => Found }).extractProduct(),
  );
}

test("structured product data wins", async ({ page }) => {
  const found = await read(
    page,
    `<html><head><title>Ignored</title>
      <link rel="canonical" href="https://shop.example/headphones">
      <script type="application/ld+json">{"@context":"https://schema.org","@graph":[
        {"@type":"BreadcrumbList"},
        {"@type":["Product"],"name":"Noise-cancelling headphones","offers":{"@type":"Offer",
         "price":"24999.00","priceCurrency":"INR","availability":"https://schema.org/InStock"}}]}
      </script></head><body><span>₹1</span></body></html>`,
  );
  expect(found).toMatchObject({
    url: "https://shop.example/headphones",
    title: "Noise-cancelling headphones",
    price: "24999.00",
    currency: "INR",
    availability: "in_stock",
    source: "structured",
  });
});

test("meta tags are used when there is no structured data", async ({ page }) => {
  const found = await read(
    page,
    `<html><head><meta property="og:title" content="Kettle">
      <meta property="product:price:amount" content="1,499">
      <meta property="product:price:currency" content="INR"></head><body></body></html>`,
  );
  expect(found).toMatchObject({ title: "Kettle", price: "1499", currency: "INR", source: "meta" });
});

test("Amazon-style price spots", async ({ page }) => {
  const found = await read(
    page,
    `<html><body><span id="productTitle"> Wireless Mouse  </span>
      <div id="corePriceDisplay_desktop_feature_div"><span class="a-price">
        <span class="a-offscreen">₹1,299.00</span><span aria-hidden="true">₹1,299</span></span></div>
      <div id="availability"><span>In stock</span></div></body></html>`,
    "https://www.amazon.in/dp/B0EXAMPLE",
  );
  expect(found).toMatchObject({
    title: "Wireless Mouse",
    price: "1299.00",
    currency: "INR",
    availability: "in_stock",
    source: "site",
  });
});

test("Flipkart-style price spots", async ({ page }) => {
  const found = await read(
    page,
    `<html><head><title>Running Shoes - Buy Online</title></head><body>
      <div class="Nx9bqj CxhGGd">₹2,499</div><div class="yRaY8j">₹3,999</div></body></html>`,
    "https://www.flipkart.com/shoes/p/itm123",
  );
  expect(found).toMatchObject({ price: "2499", currency: "INR", source: "site" });
});

test("last resort picks the prominent price, not the struck-out one", async ({ page }) => {
  const found = await read(
    page,
    `<html><head><title>Desk lamp</title></head><body>
      <p style="font-size:14px">Delivery ₹40</p>
      <span style="font-size:18px;text-decoration:line-through">₹2,999</span>
      <span style="font-size:28px">₹1,899</span>
      <span style="font-size:12px">₹99</span></body></html>`,
  );
  expect(found).toMatchObject({ price: "1899", currency: "INR", source: "page text" });
});

test("no price found is reported, not guessed", async ({ page }) => {
  const found = await read(
    page,
    `<html><head><title>About us</title></head><body>Hello</body></html>`,
  );
  expect(found).toMatchObject({ price: null, source: "none", title: "About us" });
});

test("amounts become exact minor units", async ({ page }) => {
  await page.setContent("<html><body></body></html>");
  await page.addScriptTag({ content: commonSource });
  // `const SpendWise` in a classic script is a global binding, not a window property.
  const results = await page.evaluate(`[
    SpendWise.toMinor("24999.50", "INR"),
    SpendWise.toMinor("1,299", "INR"),
    SpendWise.toMinor("0.1", "USD"),
    SpendWise.toMinor("1500", "JPY"),
    SpendWise.toMinor("1.234", "KWD"),
    SpendWise.toMinor("0", "INR"),
    SpendWise.toMinor("12abc", "INR"),
  ]`);
  expect(results).toEqual([2499950, 129900, 10, 1500, 1234, null, null]);
});
