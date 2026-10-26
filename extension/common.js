/* Settings and API calls shared by the popup and the options page. */
// eslint-disable-next-line no-unused-vars
const SpendWise = (() => {
  const EXPONENT = { JPY: 0, KRW: 0, VND: 0, BHD: 3, KWD: 3, OMR: 3, JOD: 3, TND: 3 };

  async function settings() {
    const { server, key } = await chrome.storage.local.get(["server", "key"]);
    return { server: server || "", key: key || "" };
  }

  /** "24999.50" in INR -> 2499950 (integer minor units), or null if not a positive amount. */
  function toMinor(major, currency) {
    const text = String(major || "")
      .replace(/,/g, "")
      .trim();
    if (!/^\d+(\.\d+)?$/.test(text)) return null;
    const exp = EXPONENT[currency] ?? 2;
    const [whole, frac = ""] = text.split(".");
    const minor = BigInt(whole) * 10n ** BigInt(exp) + BigInt((frac + "000").slice(0, exp) || "0");
    return minor > 0n && minor < 10n ** 15n ? Number(minor) : null;
  }

  function formatMinor(minor, currency) {
    const exp = EXPONENT[currency] ?? 2;
    try {
      return new Intl.NumberFormat(undefined, { style: "currency", currency }).format(
        minor / 10 ** exp,
      );
    } catch {
      return `${currency} ${(minor / 10 ** exp).toFixed(exp)}`;
    }
  }

  async function api(path, options = {}) {
    const { server, key } = await settings();
    if (!server || !key) throw new Error("Open the extension's options and connect it first.");
    let response;
    try {
      response = await fetch(`${server}/api/v1${path}`, {
        ...options,
        headers: {
          Authorization: `Bearer ${key}`,
          "Content-Type": "application/json",
          ...(options.headers || {}),
        },
      });
    } catch {
      throw new Error(`Can't reach ${server}. Is SpendWise running?`);
    }
    if (response.status === 401) {
      throw new Error("The key was revoked or is wrong. Create a new one in SpendWise Settings.");
    }
    const body = response.status === 204 ? null : await response.json().catch(() => null);
    if (!response.ok) {
      const detail = body && (body.detail || body.title);
      throw new Error(
        typeof detail === "string" ? detail : `SpendWise returned ${response.status}.`,
      );
    }
    return body;
  }

  return { settings, toMinor, formatMinor, api };
})();
