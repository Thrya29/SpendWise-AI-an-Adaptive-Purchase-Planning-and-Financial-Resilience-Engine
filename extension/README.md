# Save to SpendWise (browser extension)

Save a product's price from the page you're looking at — Amazon, Flipkart and most other
shops — straight into your SpendWise plan. Works in Chrome and Edge on a computer.

## Install (once)

1. In Chrome, open `chrome://extensions` (in Edge: `edge://extensions`).
2. Turn on **Developer mode** (top right).
3. Click **Load unpacked** and choose this `extension` folder.
4. Pin it: click the puzzle icon in the toolbar, then the pin next to _Save to SpendWise_.

## Connect (once)

1. In SpendWise, go to **Settings → Browser extension → Create a key** and copy the key.
   It is shown only once.
2. Right-click the extension's icon → **Options**. Enter your SpendWise address (for example
   `http://localhost:3000` on your own computer) and paste the key.
3. Click **Save and test**. The browser asks for permission to reach that one address; allow it.

## Use

1. Open a product page.
2. Click the SpendWise icon. It shows the name and price it found, and where it found them:
   the shop's product data (most reliable), the shop's price on the page, or a best guess
   marked _please check_.
3. Correct anything if needed, choose **New item** or **Existing item**, and click **Save**.

The price goes into the item's price history ("Saved from your browser"), and price-drop
alerts work as usual. For an existing item you can keep its planning price unchanged.

## What it can and can't do

- It reads a page **only when you click the button**, and only that tab. It has no access to
  other sites, and sends nothing until you click Save.
- It sends the product's name, link, price and stock status to **your SpendWise address only**.
- The key can only list your items and save prices. It can't see your money, plans or
  settings. Revoke it any time in SpendWise Settings.
- It does not check prices in the background. Visit the page again to save a newer price.
- Shops change their pages. If a price isn't found, type it in; the item still gets the link.
