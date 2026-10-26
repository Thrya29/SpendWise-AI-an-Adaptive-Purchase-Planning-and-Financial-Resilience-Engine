/* global SpendWise */
const $ = (id) => document.getElementById(id);

function status(text, kind = "") {
  $("status").textContent = text;
  $("status").className = `note ${kind}`;
}

async function load() {
  const { server, key } = await SpendWise.settings();
  $("server").value = server || "http://localhost:3000";
  $("key").value = key;
}

async function save(event) {
  event.preventDefault();
  let origin;
  try {
    const url = new URL($("server").value.trim());
    if (!/^https?:$/.test(url.protocol)) throw new Error("scheme");
    const local = ["localhost", "127.0.0.1"].includes(url.hostname);
    if (url.protocol === "http:" && !local) {
      return status("Use https:// for a server on the internet.", "warn");
    }
    origin = url.origin;
  } catch {
    return status(
      "Enter the address you open SpendWise at, e.g. https://money.example.org",
      "warn",
    );
  }
  const key = $("key").value.trim();
  if (!key.startsWith("swx_")) {
    return status("That doesn't look like an extension key (it starts with swx_).", "warn");
  }

  // Ask the browser for permission to reach this one address only.
  const granted = await chrome.permissions.request({ origins: [`${origin}/*`] });
  if (!granted)
    return status("The extension needs permission to reach your SpendWise address.", "warn");

  await chrome.storage.local.set({ server: origin, key });
  status("Testing…");
  try {
    const items = await SpendWise.api("/extension/items");
    const n = items.length;
    status(`Connected. ${n} item${n === 1 ? "" : "s"} found. You can close this tab.`, "ok");
  } catch (err) {
    status(err.message, "warn");
  }
}

$("form").addEventListener("submit", save);
load();
