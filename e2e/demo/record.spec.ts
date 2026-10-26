/**
 * Records the SpendWise walkthrough (videos) and the user manual's screenshots against a
 * running SpendWise with the demo data loaded. Not part of the test suite.
 *
 *   BASE_URL=http://localhost:3000 npx playwright test --config demo/playwright.demo.config.ts record
 *
 * Videos land in ../test-results/demo-videos, screenshots in ../../docs/manual/img.
 */
import {
  expect,
  test,
  type Browser,
  type BrowserContext,
  type Locator,
  type Page,
} from "@playwright/test";
import fs from "node:fs";
import path from "node:path";

const ROOT = path.resolve(__dirname, "../..");
const SHOTS = path.join(ROOT, "docs", "manual", "img");
const VIDEOS = path.join(ROOT, "e2e", "test-results", "demo-videos");
const EXTENSION = path.join(ROOT, "extension");
const STATEMENT = path.join(ROOT, "backend", "tests", "fixtures", "statements", "sbi_style.txt");
const ASHA = { email: "asha.demo@example.com", password: "demo-password-123" };

fs.mkdirSync(SHOTS, { recursive: true });
fs.mkdirSync(VIDEOS, { recursive: true });

// ---- Visible cursor and captions -------------------------------------------------------

const OVERLAY = () => {
  if (window !== window.top) return; // not inside frames (the extension popup)
  const install = () => {
    if (document.getElementById("sw-cursor") || !document.body) return;
    const style = document.createElement("style");
    style.textContent = `
      #sw-cursor { position: fixed; z-index: 2147483647; width: 22px; height: 22px; margin: -4px 0 0 -4px;
        pointer-events: none; transition: transform .08s; }
      #sw-cursor.down { transform: scale(.8); }
      #sw-caption { position: fixed; z-index: 2147483646; left: 50%; bottom: 22px; transform: translateX(-50%);
        max-width: 980px; width: max-content; padding: 12px 20px; border-radius: 14px; pointer-events: none;
        background: rgba(13, 17, 23, .88); color: #fff; font: 600 19px/1.35 system-ui, sans-serif;
        box-shadow: 0 8px 30px rgba(0,0,0,.25); text-align: center; }
      #sw-caption small { display: block; font-weight: 500; font-size: 15px; color: #a7f3d0; margin-bottom: 2px; }
      #sw-caption:empty { display: none; }`;
    document.head.appendChild(style);
    const cursor = document.createElement("div");
    cursor.id = "sw-cursor";
    cursor.innerHTML =
      '<svg width="22" height="22" viewBox="0 0 24 24"><path d="M3 2l7 19 2.5-7.5L20 11z" fill="#111" stroke="#fff" stroke-width="1.5"/></svg>';
    document.body.appendChild(cursor);
    const caption = document.createElement("div");
    caption.id = "sw-caption";
    caption.innerHTML = sessionStorage.getItem("sw-caption") || "";
    document.body.appendChild(caption);
    const x = sessionStorage.getItem("sw-x"),
      y = sessionStorage.getItem("sw-y");
    if (x && y) Object.assign(cursor.style, { left: `${x}px`, top: `${y}px` });
    addEventListener(
      "mousemove",
      (e) => {
        Object.assign(cursor.style, { left: `${e.clientX}px`, top: `${e.clientY}px` });
        sessionStorage.setItem("sw-x", String(e.clientX));
        sessionStorage.setItem("sw-y", String(e.clientY));
      },
      true,
    );
    addEventListener("mousedown", () => cursor.classList.add("down"), true);
    addEventListener("mouseup", () => cursor.classList.remove("down"), true);
  };
  if (document.readyState === "loading") document.addEventListener("DOMContentLoaded", install);
  else install();
};

async function say(page: Page, step: string, text: string, holdMs = 2600): Promise<void> {
  const html = `<small>${step}</small>${text}`;
  await page.evaluate((h) => {
    sessionStorage.setItem("sw-caption", h);
    const el = document.getElementById("sw-caption");
    if (el) el.innerHTML = h;
  }, html);
  await page.waitForTimeout(holdMs);
}

async function quiet(page: Page): Promise<void> {
  await page.evaluate(() => {
    sessionStorage.removeItem("sw-caption");
    const el = document.getElementById("sw-caption");
    if (el) el.innerHTML = "";
  });
}

/** A clean screenshot for the manual: no caption or cursor, and (for full pages) the sticky
 * header and action bar laid out in place instead of painted at the current scroll position. */
async function shot(page: Page, name: string, fullPage = true): Promise<void> {
  await page.evaluate((full) => {
    const style = document.createElement("style");
    style.id = "sw-shot";
    style.textContent =
      "#sw-caption,#sw-cursor{visibility:hidden!important}" +
      (full ? "header,.sticky{position:static!important}" : "");
    document.head.appendChild(style);
  }, fullPage);
  await page.screenshot({ path: path.join(SHOTS, `${name}.png`), fullPage });
  await page.evaluate(() => document.getElementById("sw-shot")?.remove());
}

async function point(page: Page, target: Locator): Promise<void> {
  await target.scrollIntoViewIfNeeded();
  const box = await target.boundingBox();
  if (box) await page.mouse.move(box.x + box.width / 2, box.y + box.height / 2, { steps: 18 });
  await page.waitForTimeout(250);
}

async function click(page: Page, target: Locator, pause = 700): Promise<void> {
  await point(page, target);
  await target.click();
  await page.waitForTimeout(pause);
}

async function type(page: Page, target: Locator, text: string): Promise<void> {
  await point(page, target);
  await target.click();
  await target.fill("");
  await target.pressSequentially(text, { delay: 45 });
  await page.waitForTimeout(250);
}

async function scrollTo(page: Page, target: Locator, pause = 600): Promise<void> {
  await target.evaluate((el) => el.scrollIntoView({ behavior: "smooth", block: "center" }));
  await page.waitForTimeout(pause);
}

async function slowScroll(page: Page, pixels: number, pause = 900): Promise<void> {
  await page.evaluate((px) => window.scrollBy({ top: px, behavior: "smooth" }), pixels);
  await page.waitForTimeout(pause);
}

async function card(page: Page, html: string, ms: number): Promise<void> {
  await page.setContent(`<!doctype html><html><head><meta charset="utf-8"><style>
    body{margin:0;height:100vh;display:grid;place-items:center;background:linear-gradient(135deg,#0f766e,#134e4a);
      font-family:system-ui,sans-serif;color:#fff;text-align:center}
    h1{font-size:64px;margin:0 0 12px;letter-spacing:-1px} h1 span{color:#99f6e4}
    p{font-size:26px;margin:6px 0;color:#d1fae5} .small{font-size:18px;color:#a7f3d0;margin-top:28px}
    ul{display:inline-block;text-align:left;font-size:24px;line-height:1.7;margin:18px 0 0}</style></head>
    <body><div>${html}</div></body></html>`);
  await page.waitForTimeout(ms);
}

async function newRecording(
  browser: Browser,
  name: string,
  size = { width: 1280, height: 720 },
  mobile = false,
) {
  const context = await browser.newContext({
    viewport: size,
    isMobile: mobile,
    hasTouch: mobile,
    deviceScaleFactor: 1,
    recordVideo: { dir: path.join(VIDEOS, `${name}-raw`), size },
    locale: "en-IN",
    timezoneId: "Asia/Kolkata",
  });
  await context.addInitScript(OVERLAY);
  const page = await context.newPage();
  return { context, page };
}

async function finish(context: BrowserContext, page: Page, name: string): Promise<void> {
  const video = page.video();
  await context.close();
  if (video) fs.copyFileSync(await video.path(), path.join(VIDEOS, `${name}.webm`));
}

async function signIn(page: Page): Promise<void> {
  await page.goto("/login");
  await type(page, page.getByLabel("Email"), ASHA.email);
  await type(page, page.getByLabel("Password"), ASHA.password);
  await click(page, page.getByRole("button", { name: "Sign in" }));
  await expect(page).toHaveURL(/dashboard/);
}

function itemCard(page: Page, name: string): Locator {
  return page
    .getByRole("listitem")
    .filter({ has: page.getByRole("heading", { name, exact: true }) })
    .first();
}

// ---- Part 1: first time ----------------------------------------------------------------

test("part 1: first time", async ({ browser }) => {
  const { context, page } = await newRecording(browser, "part1");
  await card(
    page,
    `<h1>Spend<span>Wise</span> AI</h1><p>Plan what you buy. Stay safe if salary is late.</p>
    <p class="small">A real walkthrough of the app · Part 1: your first 10 minutes</p>`,
    4000,
  );

  // 1. Sign up
  await page.goto("/register");
  await say(
    page,
    "Step 1 · Create your account",
    "Sign up with your name, email, city and main currency.",
    1500,
  );
  await type(page, page.getByLabel("Name"), "Meera Iyer");
  await type(page, page.getByLabel("Email"), `meera.demo+${Date.now()}@example.com`);
  await type(page, page.getByLabel("Password", { exact: true }), "my-safe-password");
  await type(page, page.getByLabel("Confirm password"), "my-safe-password");
  await type(page, page.getByLabel("City"), "Pune");
  await shot(page, "01-sign-up", false);
  await click(page, page.getByRole("button", { name: "Create account" }), 1500);
  await expect(page).toHaveURL(/dashboard/);
  await say(
    page,
    "Step 1 · Your dashboard",
    "A new account starts with four simple steps. The fastest way: import a bank statement.",
  );
  await shot(page, "02-dashboard-new");

  // 2. Import a bank statement
  await click(page, page.getByRole("link", { name: "Import", exact: true }), 1200);
  await say(
    page,
    "Step 2 · Import a bank statement",
    "Download a CSV statement from your net banking (3 to 6 months), then choose the file.",
  );
  await point(page, page.getByLabel("Statement file"));
  await page.getByLabel("Statement file").setInputFiles(STATEMENT);
  await page.waitForTimeout(800);
  await click(page, page.getByRole("button", { name: "Read statement" }), 1500);
  await expect(page.getByText(/rows match the running balance/)).toBeVisible();
  await scrollTo(page, page.getByRole("heading", { name: "2. Check it was read correctly" }));
  await say(
    page,
    "Step 2 · Check it",
    "SpendWise checks every row against the bank's running balance. All 79 rows match.",
  );
  await shot(page, "03-import-check");
  await scrollTo(page, page.getByRole("heading", { name: "3. Choose what to set up" }));
  await say(
    page,
    "Step 2 · Your salary and bills, found for you",
    "Salary, rent, weekly help, SIP, electricity… Rename them and tick which bills are essential.",
    3200,
  );
  await click(page, page.getByLabel("Set up Electricity"), 500);
  await scrollTo(page, page.getByRole("heading", { name: "4. Account balance" }));
  await say(
    page,
    "Step 2 · Set your balance",
    "Optionally set your account balance from the statement. Nothing is saved until you click Import.",
  );
  await shot(page, "04-import-choose");
  await click(page, page.getByRole("button", { name: /^Import \d+ items?$/ }), 1500);
  await expect(page.getByText("Imported", { exact: true })).toBeVisible();
  await page.evaluate(() => window.scrollTo({ top: 0, behavior: "smooth" }));
  await say(
    page,
    "Step 2 · Done",
    "Your income, bills and balance are set up. The statement itself is never stored.",
  );

  // 3. Money
  await click(page, page.getByRole("link", { name: "Money", exact: true }), 1500);
  await say(
    page,
    "Step 3 · Money",
    "Accounts, income and recurring bills. Add, edit or delete anything here at any time.",
  );
  await shot(page, "05-money");
  await slowScroll(page, 420);
  await say(
    page,
    "Step 3 · Money",
    "Essential bills decide the size of your emergency reserve.",
    2000,
  );

  // 4. Needs, wants & desires
  await click(page, page.getByRole("link", { name: "Needs, wants & desires" }), 1500);
  await say(
    page,
    "Step 4 · Add what you plan to buy",
    "Type it in your own words and let the assistant fill the form for you.",
    1500,
  );
  await type(
    page,
    page.getByPlaceholder(/Salon visit/),
    "Work laptop for 75k by 15 Dec, must have",
  );
  await click(page, page.getByRole("button", { name: "Fill in for me" }), 1800);
  await say(
    page,
    "Step 4 · Review the form",
    "It understood: a need, ₹75,000, by 15 December, hard deadline. You check before saving.",
  );
  await shot(page, "06-item-form", false);
  await click(page, page.locator("dialog[open]").getByRole("button", { name: "Add item" }), 1200);

  await click(page, page.getByRole("button", { name: "Add item" }).first(), 900);
  await say(
    page,
    "Step 4 · Or fill the form yourself",
    "A desire with a soft deadline: a trip.",
    1200,
  );
  const dialog = page.locator("dialog[open]");
  await type(page, dialog.getByLabel("What is it?"), "Goa trip");
  await dialog.getByLabel("Category").selectOption("desire");
  await type(page, dialog.getByLabel("Estimated price (each)"), "40000");
  await dialog.getByLabel("Target date").fill("2027-02-01");
  await page.waitForTimeout(500);
  await click(page, dialog.getByRole("button", { name: "Add item" }), 1200);

  await click(page, page.getByRole("button", { name: "Add item" }).first(), 900);
  await say(
    page,
    "Step 4 · A want with a price limit",
    "Set the most you would pay: SpendWise waits for a better price.",
    1200,
  );
  await type(page, dialog.getByLabel("What is it?"), "New phone");
  await dialog.getByLabel("Category").selectOption("want");
  await type(page, dialog.getByLabel("Estimated price (each)"), "54999");
  await type(page, dialog.getByLabel("Maximum you would pay"), "49000");
  await click(page, dialog.getByRole("button", { name: "Add item" }), 1200);
  await say(
    page,
    "Step 4 · Your list",
    "Needs, wants and desires, each with a priority, deadline and price.",
  );
  await shot(page, "07-items");

  // 5. Dashboard and What if
  await click(page, page.getByRole("link", { name: "Dashboard" }), 1800);
  await say(
    page,
    "Step 5 · Your dashboard",
    "Your balance, day by day, for the next 6 months, with every planned purchase included.",
    3000,
  );
  await shot(page, "08-dashboard");
  await click(page, page.getByLabel("Salary"), 400);
  await page.getByLabel("Salary").selectOption({ index: 2 });
  await page.waitForTimeout(600);
  await say(
    page,
    "Step 5 · What if salary is late?",
    "Try a 2-month salary delay before it happens.",
    1200,
  );
  await click(page, page.getByRole("button", { name: "Run scenario" }), 2000);
  await say(
    page,
    "Step 5 · See the risk early",
    "SpendWise shows exactly when you would dip into the reserve or run out.",
    3200,
  );
  await shot(page, "09-what-if");

  // 6. Planner
  await click(page, page.getByRole("link", { name: "Planner" }), 1500);
  await say(
    page,
    "Step 6 · The planner",
    "Choose what to stay safe against. “Salary 1 month late” is on by default.",
    2400,
  );
  await click(page, page.getByRole("button", { name: "Run planner" }).first(), 2500);
  await say(
    page,
    "Step 6 · Your plan",
    "Buy now, a safe date later, or postpone. Every decision explains why, in plain words.",
    3200,
  );
  await shot(page, "10-planner");
  await slowScroll(page, 520, 1200);
  await say(
    page,
    "Step 6 · Nothing changes until you approve",
    "Tick the changes you agree with and apply them.",
    2400,
  );
  const apply = page.getByRole("button", { name: /^Apply \d+ selected change/ });
  if ((await apply.count()) > 0 && (await apply.isEnabled())) await click(page, apply, 1500);

  // 7. Browser extension
  await click(page, page.getByRole("link", { name: "Settings" }), 1500);
  await scrollTo(page, page.getByRole("heading", { name: "Browser extension" }));
  await say(
    page,
    "Step 7 · The browser extension",
    "Save prices from Amazon, Flipkart and other shops. First, create a key.",
    1600,
  );
  await click(page, page.getByRole("button", { name: "Create a key" }), 1500);
  const key = (await page.locator("code", { hasText: "swx_" }).textContent())!.trim();
  await say(
    page,
    "Step 7 · Copy the key",
    "Paste it into the extension's options once. The key can only list items and save prices.",
  );
  await shot(page, "11-extension-key", false);

  await page.route("**/__demo-shop/**", (route) =>
    route.fulfill({ contentType: "text/html; charset=utf-8", body: DEMO_SHOP }),
  );
  await page.route("**/__extension/**", (route) => {
    const file = path.join(EXTENSION, new URL(route.request().url()).pathname.split("/").pop()!);
    const kind = file.endsWith(".js")
      ? "text/javascript"
      : file.endsWith(".css")
        ? "text/css"
        : "text/html";
    return route.fulfill({ body: fs.readFileSync(file), contentType: `${kind}; charset=utf-8` });
  });
  await page.addInitScript(
    ({ server, key: k }) => {
      const store: Record<string, string> = { server, key: k };
      Object.defineProperty(window, "chrome", {
        configurable: true,
        value: {
          storage: {
            local: {
              get: async () => ({ ...store }),
              set: async (v: object) => Object.assign(store, v),
            },
          },
          tabs: { query: async () => [{ id: 1, url: window.parent.location.href }] },
          // Runs the real price reader on the shop page this popup is shown over.
          scripting: {
            executeScript: async ({ func }: { func: () => unknown }) => [
              {
                result: (window.parent as unknown as { Function: FunctionConstructor }).Function(
                  `return (${func})()`,
                )(),
              },
            ],
          },
          permissions: { request: async () => true },
        },
      });
    },
    { server: new URL(page.url()).origin, key },
  );
  await page.goto("/__demo-shop/headphones");
  await say(
    page,
    "Step 7 · On any product page…",
    "…click the SpendWise icon in your browser's toolbar. (Sample shop page for this video.)",
    2600,
  );
  await page.evaluate(() => {
    const frame = document.createElement("iframe");
    frame.src = "/__extension/popup.html";
    frame.id = "sw-popup";
    Object.assign(frame.style, {
      position: "fixed",
      top: "8px",
      right: "16px",
      width: "380px",
      height: "400px",
      border: "1px solid #d0d7de",
      borderRadius: "12px",
      boxShadow: "0 18px 50px rgba(0,0,0,.28)",
      background: "#fff",
      zIndex: "2147483000",
    });
    document.body.appendChild(frame);
  });
  const popup = page.frameLocator("#sw-popup");
  await expect(popup.getByLabel("Product", { exact: true })).toHaveValue(/Headphones/);
  await say(
    page,
    "Step 7 · It reads the page for you",
    "Name and price come from the shop's own product data. Correct anything, then save.",
    3000,
  );
  await shot(page, "12-extension-popup", false);
  await popup.getByLabel("Type").selectOption("want");
  await click(page, popup.getByRole("button", { name: "Save to SpendWise" }), 1500);
  await expect(popup.getByRole("status")).toContainText("Added");
  await say(
    page,
    "Step 7 · Saved",
    "The item and its price are now in your plan, with the shop link and price history.",
    2600,
  );

  await page.goto("/plan");
  await page.waitForTimeout(1200);
  await scrollTo(
    page,
    page.getByRole("heading", { name: "Wireless Noise-Cancelling Headphones", exact: true }),
  );
  await say(
    page,
    "Step 7 · In your list",
    "Next time, open the same product page and the extension updates this item's price.",
    2600,
  );

  // 8. Settings
  await click(page, page.getByRole("link", { name: "Settings" }), 1500);
  await say(
    page,
    "Step 8 · Settings",
    "Your profile, emergency reserve size, reminders and privacy choices.",
    2200,
  );
  await shot(page, "13-settings");
  await scrollTo(page, page.getByRole("heading", { name: "AI assistant" }));
  await say(
    page,
    "Step 8 · AI assistant",
    "Works without any API key. Optionally add your own Claude key for richer text.",
    2800,
  );
  await quiet(page);
  await card(page, `<h1>That's the setup.</h1><p>Next: how to use SpendWise every week.</p>`, 2500);
  await finish(context, page, "part1");
});

// ---- Part 2: every week ----------------------------------------------------------------

test("part 2: every week", async ({ browser }) => {
  const { context, page } = await newRecording(browser, "part2");
  await card(
    page,
    `<h1>Every week with Spend<span>Wise</span></h1><p>Five minutes keeps your plan honest.</p>`,
    3200,
  );
  await signIn(page);
  await say(
    page,
    "Every week · Start at the dashboard",
    "Is anything at risk? The banner and the chart tell you in seconds.",
    3000,
  );

  await click(page, page.getByRole("link", { name: /Alerts/ }), 1500);
  await say(
    page,
    "Every week · Alerts",
    "Bills you can't cover, purchases due today, salary check-ins and price drops.",
    2800,
  );
  await shot(page, "14-alerts");

  await click(page, page.getByRole("link", { name: "Needs, wants & desires" }), 1500);
  await scrollTo(page, itemCard(page, "Phone upgrade"));
  await say(
    page,
    "Every week · Price history",
    "Open Prices to see every price recorded for an item, and where it came from.",
    1500,
  );
  await click(page, itemCard(page, "Phone upgrade").getByRole("button", { name: "Prices" }), 2200);
  await say(
    page,
    "Every week · Will it get cheaper?",
    "The chart shows two months of prices. The outlook estimates the chance of a sale before you need it.",
    3600,
  );
  await shot(page, "15-price-history", false);
  await page.keyboard.press("Escape");
  await page.waitForTimeout(600);

  await scrollTo(page, itemCard(page, "Noise-cancelling headphones"));
  await click(
    page,
    itemCard(page, "Noise-cancelling headphones").getByRole("button", { name: "Alternatives" }),
    1800,
  );
  await say(
    page,
    "Every week · Alternatives",
    "Premium or budget headphones? Link them and the planner buys only the best fit.",
    3200,
  );
  await shot(page, "16-alternatives", false);
  await page.keyboard.press("Escape");
  await page.waitForTimeout(500);

  await click(page, page.getByRole("link", { name: "Planner" }), 1500);
  await click(page, page.getByLabel("Salary 2 months late"), 400);
  await say(
    page,
    "Every week · Re-plan when life changes",
    "Salary late? Protect against it and run the planner again.",
    1400,
  );
  await click(page, page.getByRole("button", { name: "Run planner" }).first(), 2600);
  await say(
    page,
    "Every week · Clear decisions",
    "Wait for a better price, buy the budget alternative, or keep the reserve safe, each with its reason.",
    3400,
  );
  await shot(page, "17-planner-everyday");
  await slowScroll(page, 600, 1500);
  await slowScroll(page, 600, 1500);

  await click(page, page.getByRole("link", { name: "Savings & investing" }), 1800);
  await say(
    page,
    "Savings & investing",
    "Education, not advice: how much you could lock away, FD vs savings, and what an SIP could grow to.",
    3000,
  );
  await shot(page, "18-insights");
  const fd = page.getByRole("heading", { name: "Fixed deposit or savings account?" });
  await scrollTo(page, fd);
  await type(page, page.getByLabel("Amount").first(), "100000");
  await type(page, page.getByLabel("FD rate (% a year)"), "7.1");
  await click(page, page.getByRole("button", { name: "Compare" }), 1800);
  await say(
    page,
    "Savings & investing · FD vs savings",
    "Exact maturity amounts with your bank's real rates, including breaking the FD early.",
    3000,
  );

  await scrollTo(page, page.getByRole("heading", { name: "What could an investment grow to?" }));
  await type(page, page.getByLabel("Every month (SIP)"), "5000");
  await page.getByLabel("Assumptions from").selectOption({ index: 1 });
  await click(page, page.getByRole("button", { name: "Show possible outcomes" }), 2600);
  await say(
    page,
    "Savings & investing · A range, not a promise",
    "Weak, middle and strong markets, the chance of a loss, and the typical worst fall, from the fund's real history.",
    3600,
  );
  await shot(page, "19-simulator", false);

  await scrollTo(page, page.getByRole("heading", { name: "Gold" }));
  await say(
    page,
    "Savings & investing · Gold",
    "Reference price with a clear warning, and a jewellery bill with every charge shown.",
    2600,
  );
  await quiet(page);
  await card(
    page,
    `<h1>Spend<span>Wise</span> AI</h1><p>Plan purchases. Survive salary delays.</p>
    <p class="small">Free and open source · github.com/Thrya29</p>`,
    3500,
  );
  await finish(context, page, "part2");
});

// ---- Part 3: on a phone ----------------------------------------------------------------

test("part 3: on a phone", async ({ browser }) => {
  const { context, page } = await newRecording(browser, "part3", { width: 390, height: 844 }, true);
  await signIn(page);
  await say(page, "On your phone", "The same app, sized for phones.", 1800);
  await shot(page, "20-phone-dashboard");
  await slowScroll(page, 700, 1400);
  await click(page, page.getByRole("link", { name: "Needs, wants & desires" }), 1500);
  await say(page, "On your phone", "Add it to your home screen to use it like an app.", 1800);
  await slowScroll(page, 700, 1200);
  await click(page, page.getByRole("link", { name: "Planner" }), 1200);
  await click(page, page.getByRole("button", { name: "Run planner" }).first(), 2500);
  await shot(page, "21-phone-planner");
  await slowScroll(page, 800, 1500);
  await quiet(page);
  await finish(context, page, "part3");
});

const DEMO_SHOP = `<!doctype html><html lang="en"><head><meta charset="utf-8">
<title>Wireless Noise-Cancelling Headphones · Demo Electronics</title>
<link rel="canonical" href="https://demo-electronics.example/headphones">
<script type="application/ld+json">{"@context":"https://schema.org","@type":"Product",
"name":"Wireless Noise-Cancelling Headphones","brand":"Demo Audio",
"offers":{"@type":"Offer","price":"18999","priceCurrency":"INR","availability":"https://schema.org/InStock"}}</script>
<style>body{margin:0;font-family:system-ui,sans-serif;background:#fafafa;color:#222}
header{background:#1f2937;color:#fff;padding:14px 32px;font-weight:700;font-size:20px}
main{display:flex;gap:48px;padding:40px 32px;max-width:1000px}
.img{width:380px;height:380px;border-radius:16px;background:linear-gradient(135deg,#d1d5db,#9ca3af);display:grid;place-items:center;font-size:120px}
h1{font-size:30px;margin:0 0 10px}.price{font-size:34px;font-weight:700;color:#b45309}.mrp{color:#888;text-decoration:line-through}
.note{margin-top:30px;padding:10px 14px;background:#fff7ed;border-radius:8px;color:#9a3412;font-size:14px}
button{margin-top:22px;background:#f59e0b;border:0;border-radius:24px;padding:12px 28px;font-weight:700;font-size:16px}</style></head>
<body><header>Demo Electronics</header><main><div class="img">🎧</div><div>
<h1>Wireless Noise-Cancelling Headphones</h1><p>Demo Audio · 30-hour battery · Bluetooth 5.3</p>
<p class="mrp">₹24,999</p><p class="price">₹18,999</p><p>In stock</p><button>Add to cart</button>
<p class="note">Sample shop page made for this walkthrough. The extension works the same way on real shops.</p>
</div></main></body></html>`;
