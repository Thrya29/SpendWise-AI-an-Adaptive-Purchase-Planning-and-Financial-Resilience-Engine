/* Reads the product name and price from the page the user is looking at.
 *
 * Injected into the active tab only when the user clicks the extension (activeTab), so it
 * must be self-contained: no imports, no closures over outer variables. Most reliable first:
 *   1. structured product data (JSON-LD) that shops publish for search engines,
 *   2. product meta tags and microdata,
 *   3. known price spots on Amazon and Flipkart,
 *   4. the most prominent currency amount near the top of the page (marked "check").
 * It never sends anything anywhere; the popup shows the result for the user to confirm.
 */
// eslint-disable-next-line no-unused-vars
function extractProduct() {
  const SYMBOLS = {
    "₹": "INR",
    Rs: "INR",
    "Rs.": "INR",
    INR: "INR",
    $: "USD",
    "€": "EUR",
    "£": "GBP",
  };

  function clean(text) {
    return (text || "").replace(/\s+/g, " ").trim();
  }

  // "₹1,23,456.00" / "1,299" / "Rs. 499" / "24999" -> "123456.00" (major units) or null.
  function amount(text) {
    const match = clean(String(text)).match(/(\d[\d,]*(?:\.\d{1,2})?)/);
    if (!match) return null;
    const value = match[1].replace(/,/g, "");
    return Number(value) > 0 ? value : null;
  }

  function currencyIn(text) {
    const t = clean(text);
    for (const [symbol, code] of Object.entries(SYMBOLS)) {
      if (t.startsWith(symbol) || t.includes(` ${symbol}`)) return code;
    }
    return null;
  }

  function availabilityOf(value) {
    const v = String(value || "").toLowerCase();
    if (v.includes("outofstock") || v.includes("soldout") || v.includes("discontinued")) {
      return "out_of_stock";
    }
    if (v.includes("preorder")) return "preorder";
    if (v.includes("instock") || v.includes("limitedavailability")) return "in_stock";
    return "unknown";
  }

  function canonicalUrl() {
    const link = document.querySelector('link[rel="canonical"]');
    try {
      return link && link.href ? new URL(link.href, location.href).href : location.href;
    } catch {
      return location.href;
    }
  }

  function title() {
    const og = document.querySelector('meta[property="og:title"]');
    const amazon = document.querySelector("#productTitle");
    return clean(
      (amazon && amazon.textContent) || (og && og.content) || document.title || "",
    ).slice(0, 200);
  }

  function fromJsonLd() {
    const found = [];
    const visit = (node) => {
      if (!node || typeof node !== "object") return;
      if (Array.isArray(node)) return node.forEach(visit);
      if (node["@graph"]) visit(node["@graph"]);
      const type = [].concat(node["@type"] || []).map(String);
      if (type.some((t) => t.toLowerCase() === "product")) found.push(node);
    };
    for (const script of document.querySelectorAll('script[type="application/ld+json"]')) {
      try {
        visit(JSON.parse(script.textContent || ""));
      } catch {
        /* malformed block: ignore */
      }
    }
    for (const product of found) {
      const offers = [].concat(product.offers || []);
      for (const offer of offers) {
        const price = amount(
          offer.price ?? offer.lowPrice ?? (offer.priceSpecification || {}).price,
        );
        if (price) {
          return {
            name: clean(product.name || ""),
            price,
            currency: offer.priceCurrency || (offer.priceSpecification || {}).priceCurrency || null,
            availability: availabilityOf(offer.availability),
          };
        }
      }
    }
    return null;
  }

  function fromMeta() {
    const pick = (...selectors) => {
      for (const s of selectors) {
        const el = document.querySelector(s);
        const v = el && (el.getAttribute("content") || el.textContent);
        if (clean(v)) return clean(v);
      }
      return null;
    };
    const price = amount(
      pick(
        'meta[property="product:price:amount"]',
        'meta[property="og:price:amount"]',
        '[itemprop="price"]',
      ),
    );
    if (!price) return null;
    return {
      price,
      currency: pick(
        'meta[property="product:price:currency"]',
        'meta[property="og:price:currency"]',
        '[itemprop="priceCurrency"]',
      ),
      availability: availabilityOf(pick('[itemprop="availability"]')),
    };
  }

  function fromKnownSites() {
    const host = location.hostname;
    const selectors = host.includes("amazon.")
      ? [
          "#corePriceDisplay_desktop_feature_div .a-price .a-offscreen",
          "#corePrice_feature_div .a-price .a-offscreen",
          "#apex_desktop .a-price .a-offscreen",
          "#priceblock_dealprice",
          "#priceblock_ourprice",
          "#tp_price_block_total_price_ww .a-offscreen",
        ]
      : host.includes("flipkart.")
        ? ["div.Nx9bqj.CxhGGd", "div.Nx9bqj", "div._30jeq3._16Jk6d", "div._30jeq3"]
        : [];
    for (const s of selectors) {
      const el = document.querySelector(s);
      const text = el && clean(el.textContent);
      const price = text && amount(text);
      if (price) {
        const stock = document.querySelector("#availability");
        return {
          price,
          currency: currencyIn(text),
          availability: stock
            ? availabilityOf(clean(stock.textContent).replace(/\s/g, ""))
            : "unknown",
        };
      }
    }
    return null;
  }

  // Last resort: the largest-font currency amount in the top part of the page.
  function fromProminentText() {
    const pattern = /^(₹|Rs\.?|\$|€|£)\s?\d[\d,]*(\.\d{1,2})?$/;
    let best = null;
    const walker = document.createTreeWalker(document.body, NodeFilter.SHOW_ELEMENT);
    let checked = 0;
    for (let el = walker.nextNode(); el && checked < 5000; el = walker.nextNode()) {
      checked += 1;
      if (el.children.length > 2) continue;
      const text = clean(el.textContent);
      if (text.length > 20 || !pattern.test(text)) continue;
      const box = el.getBoundingClientRect();
      if (box.width === 0 || box.height === 0 || box.top > 1500) continue;
      const style = getComputedStyle(el);
      if (style.textDecorationLine.includes("line-through")) continue; // the old, struck price
      const size = parseFloat(style.fontSize) || 0;
      if (!best || size > best.size) best = { size, text };
    }
    if (!best) return null;
    return { price: amount(best.text), currency: currencyIn(best.text), availability: "unknown" };
  }

  const sources = [
    ["structured", fromJsonLd],
    ["meta", fromMeta],
    ["site", fromKnownSites],
    ["page text", fromProminentText],
  ];
  for (const [source, read] of sources) {
    let found = null;
    try {
      found = read();
    } catch {
      found = null;
    }
    if (found && found.price) {
      return {
        url: canonicalUrl(),
        title: clean(found.name || "") || title(),
        price: found.price,
        currency: found.currency ? String(found.currency).toUpperCase().slice(0, 3) : null,
        availability: found.availability || "unknown",
        source,
      };
    }
  }
  return {
    url: canonicalUrl(),
    title: title(),
    price: null,
    currency: null,
    availability: "unknown",
    source: "none",
  };
}
