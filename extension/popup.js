/* global SpendWise, extractProduct */
const $ = (id) => document.getElementById(id);
const CURRENCIES = ["INR", "USD", "EUR", "GBP", "AED", "SGD", "AUD", "CAD", "JPY"];
const SOURCE_TEXT = {
  structured: "Read from the shop's product data.",
  meta: "Read from the page's product tags.",
  site: "Read from the shop's price on this page.",
  "page text": "Best guess from the page. Please check the price.",
  none: "No price found on this page. Type it in.",
};
let page = null;

function status(text, kind = "") {
  $("status").textContent = text;
  $("status").className = `note ${kind}`;
}

function target() {
  return document.querySelector('input[name="target"]:checked').value;
}

function showTarget() {
  $("new-fields").hidden = target() !== "new";
  $("existing-fields").hidden = target() !== "existing";
}

async function readPage() {
  const [tab] = await chrome.tabs.query({ active: true, currentWindow: true });
  if (!tab || !/^https?:/.test(tab.url || "")) return null;
  const [result] = await chrome.scripting.executeScript({
    target: { tabId: tab.id },
    func: extractProduct,
  });
  return result && result.result;
}

function sameProduct(a, b) {
  const strip = (u) => (u || "").split(/[?#]/)[0].replace(/\/$/, "");
  return strip(a) === strip(b);
}

async function init() {
  const { server, key } = await SpendWise.settings();
  if (!server || !key) {
    $("setup").hidden = false;
    return;
  }
  $("form").hidden = false;
  for (const c of CURRENCIES) $("currency").add(new Option(c, c));

  try {
    page = await readPage();
  } catch {
    page = null;
  }
  if (!page) {
    status("Open a product page on a shop's website, then click the extension.", "warn");
    $("save").disabled = true;
    return;
  }
  $("title").value = page.title || "";
  $("price").value = page.price || "";
  if (page.currency && !CURRENCIES.includes(page.currency)) {
    $("currency").add(new Option(page.currency, page.currency));
  }
  $("currency").value = page.currency || "INR";
  $("source").textContent = SOURCE_TEXT[page.source] || "";
  $("source").className =
    page.source === "page text" || page.source === "none" ? "note warn" : "note";

  let items = [];
  try {
    items = await SpendWise.api("/extension/items");
  } catch (err) {
    status(err.message, "warn");
    return;
  }
  for (const it of items) {
    const price = SpendWise.formatMinor(it.estimated_price_minor, it.currency);
    $("item").add(new Option(`${it.name} · ${price}`, it.id));
  }
  const existing = document.querySelector('input[value="existing"]');
  const match = items.find((it) => it.url && sameProduct(it.url, page.url));
  if (match) {
    existing.checked = true;
    $("item").value = match.id;
  }
  if (!items.length) existing.disabled = true;
  showTarget();
}

async function save(event) {
  event.preventDefault();
  const currency = $("currency").value;
  const priceMinor = SpendWise.toMinor($("price").value, currency);
  if (!priceMinor) return status("Enter the price as a number, e.g. 24999 or 24999.50.", "warn");
  const body = {
    url: page.url,
    page_title: $("title").value.trim() || null,
    price_minor: priceMinor,
    currency,
    availability: page.availability || "unknown",
  };
  if (target() === "new") {
    const name = $("title").value.trim();
    if (!name) return status("Give the product a name.", "warn");
    body.new_item = {
      name: name.slice(0, 100),
      tier: $("tier").value,
      priority: Number($("priority").value),
    };
  } else {
    body.item_id = $("item").value;
    body.use_price = $("use-price").checked;
  }
  $("save").disabled = true;
  status("Saving…");
  try {
    const out = await SpendWise.api("/extension/capture", {
      method: "POST",
      body: JSON.stringify(body),
    });
    const what = out.created_item
      ? `Added “${out.item_name}”`
      : `Saved the price to “${out.item_name}”`;
    const extra = out.alerts.length ? ` ${out.alerts.join(". ")}.` : "";
    status(`${what} at ${SpendWise.formatMinor(priceMinor, currency)}.${extra}`, "ok");
  } catch (err) {
    $("save").disabled = false;
    status(err.message, "warn");
  }
}

document
  .querySelectorAll('input[name="target"]')
  .forEach((el) => el.addEventListener("change", showTarget));
$("form").addEventListener("submit", save);
init();
