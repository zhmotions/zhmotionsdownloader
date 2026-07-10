// ZH Downloader v3 — popup script

let allItems = [], currentTabId = null, currentTabUrl = "";

const listEl    = document.getElementById("item-list");
const emptyEl   = document.getElementById("empty");
const countEl   = document.getElementById("count");
const searchEl  = document.getElementById("search");
const filterEl  = document.getElementById("filter-type");
const statusEl  = document.getElementById("app-status");
const pingEl    = document.getElementById("app-ping");
const siteBar   = document.getElementById("site-bar");
const siteStatus= document.getElementById("site-status");
const siteBtn   = document.getElementById("site-toggle-btn");
const interceptEl = document.getElementById("intercept-toggle");

// ── Init ───────────────────────────────────────────────────────────────────
document.addEventListener("DOMContentLoaded", () => {
  loadItems();
  pingApp();
  setInterval(pingApp, 4000);

  searchEl.addEventListener("input", render);
  filterEl.addEventListener("change", render);

  // Intercept toggle
  interceptEl.addEventListener("change", () => {
    chrome.runtime.sendMessage(
      { type:"ZH_TOGGLE_INTERCEPT", value: interceptEl.checked },
      () => showStatus(interceptEl.checked ? "✓ Download interception ON" : "Download interception OFF",
                       interceptEl.checked)
    );
  });

  // Site toggle
  siteBtn.addEventListener("click", () => {
    chrome.contextMenus && chrome.tabs.query({ active:true, currentWindow:true }, tabs => {
      if (!tabs[0]) return;
      chrome.runtime.sendMessage({ type:"ZH_GET_TAB" }, res => {
        if (!res) return;
        loadItems();
      });
    });
    // Trigger context menu toggle via background
    chrome.runtime.sendMessage({ type:"ZH_SITE_TOGGLE" });
    setTimeout(loadItems, 300);
  });

  document.getElementById("btn-clear").addEventListener("click", () => {
    if (!currentTabId) return;
    chrome.runtime.sendMessage({ type:"ZH_CLEAR", tabId:currentTabId });
    allItems = []; render();
  });

  document.getElementById("btn-page").addEventListener("click", () => {
    chrome.runtime.sendMessage({ type:"ZH_PAGE_URL" }, res => {
      showStatus(res?.ok ? "✓ Sent page to app!" : "✗ App not running", res?.ok);
    });
  });
});

// ── Load tab info ──────────────────────────────────────────────────────────
function loadItems() {
  chrome.runtime.sendMessage({ type:"ZH_GET_TAB" }, res => {
    if (!res) return;
    currentTabId  = res.tabId;
    currentTabUrl = res.url || "";
    allItems      = res.items || [];
    interceptEl.checked = res.intercept !== false;

    // Site bar
    try {
      const host = new URL(currentTabUrl).hostname;
      if (res.isDisabled) {
        siteBar.style.display = "flex";
        siteStatus.textContent = `Disabled on ${host}`;
        siteBtn.textContent    = "Enable";
      } else {
        siteBar.style.display = "flex";
        siteStatus.textContent = `Active on ${host}`;
        siteBtn.textContent    = "Disable";
      }
    } catch { siteBar.style.display = "none"; }

    render();
  });
}

// Live updates
chrome.runtime.onMessage.addListener(msg => {
  if (msg.type === "ZH_UPDATED" && msg.tabId === currentTabId) {
    allItems = msg.items || [];
    render();
  }
});

// ── Render list ────────────────────────────────────────────────────────────
function render() {
  const q    = searchEl.value.trim().toLowerCase();
  const type = filterEl.value;
  const filtered = allItems.filter(item => {
    if (type !== "all" && item.type !== type) return false;
    if (q && !item.name.toLowerCase().includes(q) && !item.url.toLowerCase().includes(q)) return false;
    return true;
  });

  listEl.innerHTML = "";
  emptyEl.style.display  = filtered.length === 0 ? "block" : "none";
  countEl.textContent    = `${filtered.length} item${filtered.length !== 1 ? "s" : ""}`;

  filtered.forEach(item => {
    const li = document.createElement("li");
    li.className = "item";

    const isStream = ["HLS","DASH","STREAM"].includes(item.type);
    const isVideo  = ["MP4","WEBM","MKV","VIDEO","HLS","DASH","STREAM"].includes(item.type);

    const badge = document.createElement("span");
    badge.className   = `type-badge badge-${item.type}`;
    badge.textContent = item.type;

    const info = document.createElement("div");
    info.className = "item-info";
    const name = document.createElement("span");
    name.className   = "item-name";
    name.title       = item.url;
    name.textContent = item.name || shortUrl(item.url);
    const meta = document.createElement("span");
    meta.className   = "item-meta";
    meta.textContent = [item.sizeStr, item.source === "dom" ? "DOM" : "Network"].filter(Boolean).join(" · ");
    info.append(name, meta);

    const actions = document.createElement("div");
    actions.className = "item-actions";

    // Send to app (streams + video)
    if (isStream || isVideo) {
      const app = document.createElement("button");
      app.className   = "btn-app";
      app.textContent = "📤 App";
      app.onclick = () => {
        chrome.runtime.sendMessage({ type:"ZH_SEND_TO_APP", url:item.url, referer:item.referer||item.url }, res => {
          showStatus(res?.ok ? "✓ Sent to app!" : "✗ App not running", res?.ok);
        });
      };
      actions.appendChild(app);
    }

    // Direct download (non-stream)
    if (!isStream) {
      const dl = document.createElement("button");
      dl.className   = "btn-dl";
      dl.textContent = "⬇";
      dl.title       = "Download via browser";
      dl.onclick = () => {
        chrome.runtime.sendMessage({ type:"ZH_DOWNLOAD", item }, res => {
          showStatus(res?.ok ? "✓ Downloading!" : "✗ Failed: "+(res?.err||""), res?.ok);
        });
      };
      actions.appendChild(dl);
    }

    // Copy URL
    const copy = document.createElement("button");
    copy.className   = "btn-copy";
    copy.textContent = "🔗";
    copy.title       = "Copy URL";
    copy.onclick = () => {
      navigator.clipboard.writeText(item.url).then(() => {
        copy.textContent = "✓";
        setTimeout(() => copy.textContent = "🔗", 1500);
      });
    };
    actions.appendChild(copy);

    li.append(badge, info, actions);
    listEl.appendChild(li);
  });
}

// ── App ping ───────────────────────────────────────────────────────────────
async function pingApp() {
  pingEl.className   = "ping-checking";
  pingEl.textContent = "● Checking…";
  chrome.runtime.sendMessage({ type:"ZH_PING_APP" }, res => {
    if (res?.ok) {
      pingEl.className   = "ping-ok";
      pingEl.textContent = "● App online";
    } else {
      pingEl.className   = "ping-err";
      pingEl.textContent = "● App offline";
    }
  });
}

// ── Status toast ───────────────────────────────────────────────────────────
let stTimer;
function showStatus(msg, ok) {
  statusEl.textContent = msg;
  statusEl.className   = "app-status show " + (ok ? "ok" : "err");
  clearTimeout(stTimer);
  stTimer = setTimeout(() => statusEl.className = "app-status", 3000);
}

function shortUrl(url) {
  try {
    const u = new URL(url);
    return u.hostname + u.pathname.slice(0,40);
  } catch { return url.slice(0,60); }
}
