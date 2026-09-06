// ZH Downloader v3 — background service worker
// Full browser integration: intercept downloads, context menu, media capture

const MEDIA_EXT   = /\.(mp4|m3u8|mpd|webm|mov|mkv|flv|ts|m4v|m4a|mp3|aac|ogg|wav|flac)(\?|$)/i;
const FILE_EXT    = /\.(pdf|zip|rar|7z|exe|dmg|pkg|msi|apk|iso|tar|gz|bz2|docx?|xlsx?|pptx?|jpg|jpeg|png|gif|webp|svg|epub|torrent)(\?|$)/i;
const SEGMENT_EXT = /\.(ts|m4s|fmp4)(\?|$)/i;
const SKIP_KW     = /(\/seg\/|\/chunk\/|seg-\d+\.|chunk-\d+\.|\.vtt(\?|$)|\.srt(\?|$)|thumbnail|poster|sprite)/i;
// Bare words (manifest|playlist|master|stream|preview) matched anywhere in the
// URL, so every site's manifest.json / preview.png landed in the list and
// inflated the badge. Real streams are identified by extension, path segment or
// content-type (x-mpegURL below) — which also covers extensionless HLS.
const STREAM_KW   = /(\.m3u8|\.mpd|\/hls\/|\/dash\/|\/(master|playlist|index)[._-]|videoplayback|[?&](m3u8|mpd)=)/i;
const MEDIA_TYPE  = /^(video|audio)\//i;

const STOCK_SITES = [
  "artgrid.io","artlist.io","storyblocks.com","pond5.com","shutterstock.com",
  "istockphoto.com","motionarray.com","envato.com","videohive.net",
  "vimeo.com","wistia.com","brightcove","jwplatform","akamaized.net","cloudfront.net"
];

const tabState  = new Map();
let   intercept = true;   // global intercept toggle (ON by default — safer narrow scope in content.js)
let   whitelist = [];     // sites where ZH is disabled

// ── Storage: load settings ─────────────────────────────────────────────────
chrome.storage.local.get(["intercept","whitelist"], r => {
  intercept = r.intercept !== false;  // default ON (user can disable in popup)
  whitelist = r.whitelist || [];
});

// React to settings changes from popup
chrome.storage.onChanged.addListener((changes) => {
  if (changes.intercept) intercept = changes.intercept.newValue !== false;
  if (changes.whitelist) whitelist = changes.whitelist.newValue || [];
});

// ── Tab state ──────────────────────────────────────────────────────────────
// MV3 shuts this service worker down after ~30s idle and `tabState` dies with
// it. The overlay pill asks for those sniffed streams the moment you click
// Download on Artlist/Artgrid — if the worker had slept, the list came back
// EMPTY and the click silently fell back to a page URL yt-dlp can't extract.
// storage.session is in-memory (never touches disk, cleared when the browser
// closes) and DOES survive worker restarts, so mirror the map into it.
const SESSION = (chrome.storage && chrome.storage.session) || null;

let restoreDone = false;

// Writes the WHOLE map, so it must never run before the restore below has
// merged what was already saved — a woken worker that persists first would
// publish its half-empty map and wipe every other tab's sniffed streams.
// Only that brief window defers; once restored it writes straight through, so
// a worker killed right after sniffing still has the stream on disk.
function persist() {
  if (!SESSION) return;
  if (!restoreDone) { restored.then(persist); return; }
  const o = {};
  for (const [k, v] of tabState) if (v && v.length) o[k] = v.slice(0, 40);
  SESSION.set({ tabState: o }).catch(() => {});
}

// Every path that answers the content script must await this first, or a
// just-woken worker reports "nothing sniffed" while the data is still loading.
const restored = (async () => {
  if (!SESSION) return;
  try {
    const r = await SESSION.get("tabState");
    const o = r.tabState || {};
    for (const k in o) {
      const id = +k, saved = o[k] || [];
      const live = tabState.get(id);
      // A webRequest can wake the worker and fill this tab's bucket before the
      // read above resolves. Skipping the tab then would throw away exactly the
      // streams this whole mechanism exists to keep, so merge instead — newly
      // sniffed items stay on top, saved ones follow.
      if (!live || !live.length) { tabState.set(id, saved); continue; }
      const seen = new Set(live.map(i => i && i.url));
      for (const it of saved) if (it && !seen.has(it.url)) live.push(it);
      if (live.length > 100) live.length = 100;
    }
  } catch {}
  restoreDone = true;
})();

function getTab(id) {
  if (!tabState.has(id)) tabState.set(id, []);
  return tabState.get(id);
}

function isWanted(url, ctype, initiator) {
  if (!url) return false;
  try { new URL(url); } catch { return false; }
  if (SEGMENT_EXT.test(url) && !url.includes("master") && !url.includes("playlist")) return false;
  if (SKIP_KW.test(url)) return false;
  if (STREAM_KW.test(url)) return true;
  if (ctype && MEDIA_TYPE.test(ctype)) return true;
  if (MEDIA_EXT.test(url)) return true;
  if (FILE_EXT.test(url)) return true;
  if (initiator && STOCK_SITES.some(s => initiator.includes(s))) {
    if (url.includes("preview") || url.includes("sample")) return true;
  }
  if (ctype && (ctype.includes("octet-stream") || ctype.includes("x-mpegURL"))) return true;
  return false;
}

function classifyUrl(url, ctype) {
  const u = url.toLowerCase();
  if (u.includes(".m3u8") || (ctype||"").includes("mpegURL")) return "HLS";
  if (u.includes(".mpd")  || (ctype||"").includes("dash+xml")) return "DASH";
  if (u.includes("videoplayback") || u.includes("googlevideo")) return "STREAM";
  if (u.match(/\.(mp4|mov|mkv|webm|flv)(\?|$)/)) return "MP4";
  if (u.match(/\.(mp3|m4a|aac|wav|flac|ogg)(\?|$)/)) return "AUDIO";
  if (u.match(/\.pdf(\?|$)/)) return "PDF";
  if (u.match(/\.(zip|rar|7z)(\?|$)/)) return "ZIP";
  if ((ctype||"").startsWith("video/")) return "VIDEO";
  if ((ctype||"").startsWith("audio/")) return "AUDIO";
  return "FILE";
}

function nameFromUrl(url) {
  try {
    const u = new URL(url);
    return decodeURIComponent(u.pathname.split("/").filter(Boolean).pop() || u.hostname).slice(0,100);
  } catch { return url.slice(0,60); }
}

function fmtSize(b) {
  if (!b) return "";
  if (b > 1073741824) return (b/1073741824).toFixed(1)+" GB";
  if (b > 1048576)    return (b/1048576).toFixed(1)+" MB";
  if (b > 1024)       return (b/1024).toFixed(0)+" KB";
  return b+" B";
}

function push(tabId, item) {
  const bucket = getTab(tabId);
  if (bucket.some(b => b.url === item.url)) return;
  bucket.unshift(item);
  if (bucket.length > 100) bucket.length = 100;
  updateBadge(tabId);
  persist();
  chrome.runtime.sendMessage({ type:"ZH_UPDATED", tabId, items:bucket }).catch(()=>{});
}

function updateBadge(tabId) {
  const n = getTab(tabId).length;
  chrome.action.setBadgeBackgroundColor({ color:"#ff6b35" });
  chrome.action.setBadgeText({ tabId, text: n>0 ? String(n) : "" });
}

// ── Network media capture ──────────────────────────────────────────────────
chrome.webRequest.onResponseStarted.addListener(details => {
  if (details.tabId < 0) return;
  const h   = (details.responseHeaders||[]).reduce((m,h) => { m[h.name.toLowerCase()]=h.value; return m; }, {});
  const ct  = h["content-type"] || "";
  const ini = details.initiator || "";
  if (!isWanted(details.url, ct, ini)) return;
  const size = parseInt(h["content-length"]||"0", 10);
  push(details.tabId, {
    url:     details.url,
    type:    classifyUrl(details.url, ct),
    mime:    ct,
    size,    sizeStr: fmtSize(size),
    name:    nameFromUrl(details.url),
    source:  "network",
    // the PAGE that pulled the stream, not the stream itself — hotlink-checked
    // CDNs reject a request whose Referer is the media URL
    referer: details.initiator || details.url,
    ts:      Date.now()
  });
}, { urls:["<all_urls>"] }, ["responseHeaders"]);

// ── Intercept browser downloads → send to app ──────────────────────────────
// Never intercept these sites
const SKIP_HOSTS = [
  "github.com", "githubusercontent.com", "githubassets.com",
  "127.0.0.1", "localhost",
  "google.com", "googleapis.com", "gstatic.com",
  "apple.com", "microsoft.com", "windows.com",
  "chrome.google.com", "extensions",
];

// Only intercept these file types
const MEDIA_RE = /\.(mp4|webm|mkv|mov|flv|avi|mp3|m4a|wav|flac|aac|ogg|m3u8|mpd|ts|m4s)(\?|$)/i;
const FILE_RE  = /\.(pdf|zip|rar|7z|exe|dmg|pkg|msi|apk|iso|tar\.gz|tar|gz|bz2|epub|torrent)(\?|$)/i;

// A download is worth taking away from the browser only when the URL ITSELF is
// clearly a file — an extension in the path, or (checked earlier) a media
// content-type. Many sites (Canva, Figma, Google Docs, "export" / "render" /
// "generate" endpoints everywhere) return the file from a server-side JOB: you
// click Download, an API call fires whose URL is a bare id — and Chrome still
// guesses a media *filename* for that JSON reply (Canva's `e89a9216-…` failed
// row). If we take THAT, the app gets a URL that returns JSON, not bytes, and
// the real download never happened. So: bare URL path + filename-only match =>
// leave it with the browser. The browser has the session and always finishes;
// the real file, when it downloads from the CDN a moment later, has a proper
// extension and we take that one.
function _pathHasExt(u) {
  try { return /\.[a-z0-9]{2,5}$/i.test(new URL(u).pathname); } catch { return false; }
}

chrome.downloads.onCreated.addListener(async downloadItem => {
  if (!intercept) return;
  const url = downloadItem.url || downloadItem.finalUrl || "";
  if (!url || url.startsWith("blob:") || url.startsWith("data:")) return;

  // Skip non-media/file sites
  let host = "";
  try {
    host = new URL(url).hostname;
    if (SKIP_HOSTS.some(s => host.includes(s))) return;
  } catch { return; }

  // Only intercept actual media/file downloads
  const fname = downloadItem.filename || "";
  const urlIsFile = MEDIA_RE.test(url) || FILE_RE.test(url);
  const isMedia = urlIsFile || MEDIA_RE.test(fname);
  const isFile  = urlIsFile || FILE_RE.test(fname);
  if (!isMedia && !isFile) return;

  // Filename-only match on a bare URL path = an API / export-job endpoint, not a
  // file (see _pathHasExt note above). Leave it with the browser — but remember
  // its id: when the browser finishes the *real* file, adopt it into the app so
  // Canva/Figma/… downloads still get renamed / transcoded / logged.
  if (!urlIsFile && !_pathHasExt(url)) {
    try {
      const t = await chrome.tabs.query({ active:true, currentWindow:true });
      const pageUrl = t[0]?.url || "";
      if (SESSION && !whitelist.some(w => pageUrl.includes(w))) {
        const { adopt = {} } = await SESSION.get("adopt");
        const cut = Date.now() - 60*60*1000;              // drop entries > 1h old
        for (const k of Object.keys(adopt)) if (adopt[k].ts < cut) delete adopt[k];
        adopt[downloadItem.id] = { url, pageUrl, ts: Date.now() };
        SESSION.set({ adopt }).catch(()=>{});
      }
    } catch {}
    return;
  }

  // Check whitelist
  let tabUrl = "";
  try {
    const tabs = await chrome.tabs.query({ active:true, currentWindow:true });
    tabUrl = tabs[0]?.url || "";
    if (whitelist.some(w => tabUrl.includes(w))) return;
  } catch {}

  // Cancel and send to app
  try {
    await chrome.downloads.cancel(downloadItem.id);
    await chrome.downloads.erase({ id: downloadItem.id });
  } catch {}

  // src:"intercept" marks this as a download we took away from the browser. If
  // the app never comes up, flushWhenReady() hands it back rather than losing
  // it — the old `if (!ok.ok) chrome.downloads.download(url)` guard here could
  // never fire, because sendToApp resolves {ok:true} as soon as it queues.
  await sendToApp(url, tabUrl || undefined, "", "", "intercept");
});

// ── Adopt: a render-job file we stepped aside from has finished downloading ──
// The browser did the work (it has the session); we hand the finished file to
// the app so it still runs through rename / transcode / history.
chrome.downloads.onChanged && chrome.downloads.onChanged.addListener(async delta => {
  if (!SESSION || !delta || !delta.state) return;        // ignore byte-progress deltas
  const { adopt = {} } = await SESSION.get("adopt");
  const meta = adopt[delta.id];
  if (!meta) return;
  const st = delta.state.current;
  if (st !== "complete") {
    if (st === "interrupted") { delete adopt[delta.id]; SESSION.set({ adopt }).catch(()=>{}); }
    return;
  }
  delete adopt[delta.id]; SESSION.set({ adopt }).catch(()=>{});
  let path = "";
  try { const r = await chrome.downloads.search({ id: delta.id }); path = (r[0] || {}).filename || ""; } catch {}
  if (!path) return;
  let title = "";
  try {
    const base = (meta.pageUrl || "").split("?")[0];
    const tabs = await chrome.tabs.query({});
    const tab = tabs.find(x => x.url === meta.pageUrl) || tabs.find(x => (x.url || "").startsWith(base));
    title = (tab && tab.title) || "";
  } catch {}
  try {
    await fetch("http://127.0.0.1:9613/adopt", {
      method: "POST",
      body: JSON.stringify({ path, url: meta.url, referer: meta.pageUrl, title }),
    });
    notify("Sent to ZH Downloader", path.split(/[\\/]/).pop());
  } catch {}   // app closed — the file is on disk in Downloads, nothing lost
});

// ── Context menu ───────────────────────────────────────────────────────────
// When the browser/extension wakes, push any downloads queued while the app was closed.
chrome.runtime.onStartup.addListener(() => { try { flushWhenReady(); } catch {} });

// Re-inject the content script into every already-open tab whenever the
// extension is installed/updated/reloaded. Chrome does NOT do this automatically
// — without it, tabs opened before a reload run a dead ("orphaned") script and
// the Download button silently does nothing until you refresh. This removes that
// manual-refresh step. content.js guards with window.__zhLoaded so re-injecting
// into a fresh tab is a harmless no-op.
function reinjectAllTabs() {
  try {
    chrome.tabs.query({}, (tabs) => {
      for (const t of (tabs || [])) {
        if (!t.id || !t.url || !/^https?:/i.test(t.url)) continue;
        chrome.scripting.executeScript({ target: { tabId: t.id }, files: ["content.js"] }).catch(() => {});
      }
    });
  } catch (e) {}
}

chrome.runtime.onInstalled.addListener(() => {
  try { flushWhenReady(); } catch {}
  try { reinjectAllTabs(); } catch {}
  // Main download option
  chrome.contextMenus.create({
    id:       "zh-download-link",
    title:    "⬇  Download with ZH Downloader",
    contexts: ["link","video","audio","image"],
  });
  chrome.contextMenus.create({
    id:       "zh-download-page",
    title:    "⬇  Download this page (video/audio)",
    contexts: ["page"],
  });
  chrome.contextMenus.create({
    id:       "zh-separator",
    type:     "separator",
    contexts: ["link","video","audio","image","page"],
  });
  chrome.contextMenus.create({
    id:       "zh-toggle",
    title:    "⏸  Disable ZH Downloader on this site",
    contexts: ["page"],
  });
  chrome.contextMenus.create({
    id:       "zh-open-app",
    title:    "🚀  Open ZH Downloader app",
    contexts: ["page","link"],
  });
});

chrome.contextMenus.onClicked.addListener(async (info, tab) => {
  if (info.menuItemId === "zh-download-link") {
    const url = info.linkUrl || info.srcUrl || info.pageUrl;
    await sendToApp(url, info.pageUrl);
  }
  else if (info.menuItemId === "zh-download-page") {
    await sendToApp(tab.url);
  }
  else if (info.menuItemId === "zh-toggle") {
    try {
      const host = new URL(tab.url).hostname;
      const idx  = whitelist.indexOf(host);
      if (idx >= 0) {
        whitelist.splice(idx, 1);
        chrome.contextMenus.update("zh-toggle", { title:"⏸  Disable ZH Downloader on this site" });
        notify("ZH Downloader enabled", `Active on ${host}`);
      } else {
        whitelist.push(host);
        chrome.contextMenus.update("zh-toggle", { title:"▶  Enable ZH Downloader on this site" });
        notify("ZH Downloader disabled", `Paused on ${host}`);
      }
      chrome.storage.local.set({ whitelist });
    } catch {}
  }
  else if (info.menuItemId === "zh-open-app") {
    // Ping app — if offline show notification
    const r = await pingApp();
    if (!r) notify("ZH Downloader", "App is not running. Open the desktop app first.");
  }
});

// ── Messages from popup/content ────────────────────────────────────────────
chrome.runtime.onMessage.addListener((msg, sender, sendResponse) => {
  if (!msg?.type) return;

  if (msg.type === "ZH_DOM" && sender.tab) {
    for (const item of msg.items||[]) {
      push(sender.tab.id, {
        url: item.url, type: classifyUrl(item.url, item.mime||""),
        mime: item.mime||"", size:0, sizeStr:"",
        name: item.name || nameFromUrl(item.url),
        source:"dom", title: item.title||"", ts: Date.now()
      });
    }
  }

  if (msg.type === "ZH_GET_TAB") {
    // await `restored` first: on a freshly-woken service worker the sniffed
    // streams are still being read back from storage.session, and answering
    // early is what made Artlist/Artgrid downloads randomly fail.
    (async () => {
      await restored;
      try {
        const tabs = await chrome.tabs.query({ active:true, currentWindow:true });
        if (!tabs.length) { sendResponse({ tabId:null, items:[] }); return; }
        const tab = tabs[0];
        sendResponse({
          tabId: tab.id, url: tab.url, title: tab.title,
          items: getTab(tab.id),
          intercept,
          isDisabled: whitelist.some(w => (tab.url||"").includes(w))
        });
      } catch { sendResponse({ tabId:null, items:[] }); }
    })();
    return true;
  }

  if (msg.type === "ZH_CLEAR" && msg.tabId != null) {
    tabState.set(msg.tabId, []); updateBadge(msg.tabId); persist();
  }

  // Popup's Enable/Disable-on-this-site button. Same whitelist the context-menu
  // toggle uses (whitelist = hosts where ZH is disabled). Was never handled —
  // the popup button did nothing.
  if (msg.type === "ZH_SITE_TOGGLE") {
    chrome.tabs.query({ active:true, currentWindow:true }, tabs => {
      try {
        const host = new URL(tabs[0].url).hostname;
        const idx  = whitelist.indexOf(host);
        if (idx >= 0) whitelist.splice(idx, 1); else whitelist.push(host);
        chrome.storage.local.set({ whitelist });
        sendResponse({ ok:true, disabled: idx < 0 });
      } catch (e) { sendResponse({ ok:false }); }
    });
    return true;
  }

  if (msg.type === "ZH_SEND_TO_APP") {
    sendToApp(msg.url, msg.referer, msg.fmt, msg.title).then(r => sendResponse(r));
    return true;
  }

  if (msg.type === "ZH_DOWNLOAD") {
    handleDownload(msg.item).then(r => sendResponse(r));
    return true;
  }

  if (msg.type === "ZH_PAGE_URL") {
    chrome.tabs.query({ active:true, currentWindow:true }, tabs => {
      if (!tabs.length) { sendResponse({ok:false}); return; }
      sendToApp(tabs[0].url).then(r => sendResponse(r));
    });
    return true;
  }

  if (msg.type === "ZH_TOGGLE_INTERCEPT") {
    intercept = msg.value;
    chrome.storage.local.set({ intercept });
    sendResponse({ ok:true, intercept });
  }

  if (msg.type === "ZH_PING_APP") {
    pingApp().then(ok => sendResponse({ ok }));
    return true;
  }
});

// ── Send to desktop app ────────────────────────────────────────────────────
async function postToApp(url, referer, fmt, title) {
  const r = await fetch("http://127.0.0.1:9613/download", {
    method:"POST",
    headers:{ "Content-Type":"application/json" },
    body: JSON.stringify({ url, referer: referer||url, fmt: fmt||"", title: title||"" }),
  });
  return r.json();
}

async function sendToApp(url, referer, fmt, title, src) {
  try {
    const d = await postToApp(url, referer, fmt, title);
    if (d.ok) notify("Sent to ZH Downloader", url.slice(0,60)+"…");
    return d;
  } catch(e) {
    // App is closed → queue it, launch the app, flush when the bridge is up.
    await queuePending(url, referer, src);
    launchApp();
    notify("Opening ZH Downloader…", "Your download will start automatically.");
    flushWhenReady();
    return { ok:true, queued:true };
  }
}

// pending queue (survives until the app comes online)
// TTL: onStartup flushes this queue, and without an expiry a link queued days
// ago started downloading out of nowhere the next time the browser opened.
const PENDING_TTL = 6 * 60 * 60 * 1000;   // 6h
const isFresh = p => !p.ts || (Date.now() - p.ts) < PENDING_TTL;

async function queuePending(url, referer, src) {
  const { pending = [] } = await chrome.storage.local.get("pending");
  const fresh = pending.filter(isFresh);
  if (!fresh.some(p => p.url === url)) {
    fresh.push({ url, referer: referer||url, src: src||"", ts: Date.now() });
  }
  await chrome.storage.local.set({ pending: fresh });
}

// launch the desktop app via its URL scheme (only opens it; no data needed).
// Must be an ACTIVE tab so the browser's "Open ZH Downloader?" prompt is visible —
// closing it too early (old bug) dismissed the prompt before the app launched.
function launchApp() {
  try {
    chrome.tabs.create({ url: "zhdownloader://open", active: true }, (tab) => {
      if (tab) setTimeout(() => { try { chrome.tabs.remove(tab.id); } catch {} }, 8000);
    });
  } catch {}
}

// poll the bridge; once it answers, send everything that was queued
let _flushing = false;
async function flushWhenReady() {
  if (_flushing) return; _flushing = true;
  try {
    for (let i = 0; i < 30; i++) {                 // ~60s window
      if (await pingApp()) {
        const { pending = [] } = await chrome.storage.local.get("pending");
        const fresh = pending.filter(isFresh);
        for (const p of fresh) { try { await postToApp(p.url, p.referer); } catch {} }
        await chrome.storage.local.set({ pending: [] });
        if (fresh.length) notify("ZH Downloader ready", `Sent ${fresh.length} download(s).`);
        return;
      }
      await new Promise(r => setTimeout(r, 2000));
    }
    // App never came up. Downloads we cancelled in the browser would just
    // vanish, so hand those back to the browser. Everything else stays queued
    // (right-click sends, stream URLs) until the app runs or the TTL drops it.
    const { pending = [] } = await chrome.storage.local.get("pending");
    const keep = [];
    let handed = 0;
    for (const p of pending) {
      if (!isFresh(p)) continue;
      if (p.src === "intercept") {
        try { chrome.downloads.download({ url: p.url }); handed++; } catch {}
      } else keep.push(p);
    }
    await chrome.storage.local.set({ pending: keep });
    if (handed) notify("ZH Downloader didn't start", `${handed} download(s) handed back to the browser.`);
  } finally { _flushing = false; }
}

// Heartbeat: the app only learns the extension exists when it receives a ping
// carrying an extension Origin, and that used to happen solely while the popup
// was open — so the app kept reporting "not detected". One alarm a minute is
// enough to keep the app's status honest.
try {
  chrome.alarms.create("zh-ping", { periodInMinutes: 1 });
  chrome.alarms.onAlarm.addListener(a => { if (a.name === "zh-ping") pingApp(); });
} catch (e) { /* alarms unavailable — popup ping still covers it */ }

async function pingApp() {
  try {
    const r = await fetch("http://127.0.0.1:9613/ping",
                          { signal: AbortSignal.timeout(1500) });
    const d = await r.json();
    return d.ok;
  } catch { return false; }
}

async function handleDownload(item) {
  if (!item?.url) return { ok:false };
  if (["HLS","DASH","STREAM"].includes(item.type)) {
    return sendToApp(item.url, item.referer||item.url);
  }
  try {
    const id = await chrome.downloads.download({
      url: item.url, filename: item.name || nameFromUrl(item.url), saveAs:false
    });
    return { ok:true, id };
  } catch(e) { return { ok:false, err:String(e) }; }
}

function notify(title, body) {
  chrome.notifications.create({
    type:"basic", iconUrl:"icons/icon128.png", title, message: body||""
  });
}

// ── Cleanup ────────────────────────────────────────────────────────────────
chrome.tabs.onRemoved.addListener(tabId => { tabState.delete(tabId); persist(); });
if (chrome.webNavigation) {
  chrome.webNavigation.onCommitted.addListener(d => {
    if (d.frameId === 0) { tabState.set(d.tabId, []); updateBadge(d.tabId); persist(); }
  });
  // SPA route changes (Artgrid/Artlist/YouTube navigate via history.pushState —
  // no onCommitted fires). Without this, streams sniffed on PREVIOUS clips pile
  // up in the tab list and the pill's auto-pick grabs a STALE master m3u8 →
  // "same video downloads again / wrong video downloads".
  chrome.webNavigation.onHistoryStateUpdated.addListener(d => {
    if (d.frameId === 0) { tabState.set(d.tabId, []); updateBadge(d.tabId); persist(); }
  });
}
