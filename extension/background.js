// ZH Downloader v3 — background service worker
// Full browser integration: intercept downloads, context menu, media capture

const MEDIA_EXT   = /\.(mp4|m3u8|mpd|webm|mov|mkv|flv|ts|m4v|m4a|mp3|aac|ogg|wav|flac)(\?|$)/i;
const FILE_EXT    = /\.(pdf|zip|rar|7z|exe|dmg|pkg|msi|apk|iso|tar|gz|bz2|docx?|xlsx?|pptx?|jpg|jpeg|png|gif|webp|svg|epub|torrent)(\?|$)/i;
const SEGMENT_EXT = /\.(ts|m4s|fmp4)(\?|$)/i;
const SKIP_KW     = /(\/seg\/|\/chunk\/|seg-\d+\.|chunk-\d+\.|\.vtt(\?|$)|\.srt(\?|$)|thumbnail|poster|sprite)/i;
const STREAM_KW   = /(\.m3u8|\.mpd|manifest|playlist|master|stream|preview|hls|dash|videoplayback)/i;
const MEDIA_TYPE  = /^(video|audio)\//i;

const STOCK_SITES = [
  "artgrid.io","artlist.io","storyblocks.com","pond5.com","shutterstock.com",
  "istockphoto.com","motionarray.com","envato.com","videohive.net",
  "vimeo.com","wistia.com","brightcove","jwplatform","akamaized.net","cloudfront.net"
];

const VIDEO_HOSTS = [
  "youtube.com","youtu.be","vimeo.com","tiktok.com","instagram.com",
  "facebook.com","fb.watch","twitter.com","x.com","twitch.tv",
  "reddit.com","dailymotion.com","soundcloud.com","bilibili.com",
  "rumble.com","streamable.com","artgrid.io","artlist.io","pinterest.com"
];

const tabState  = new Map();
let   intercept = true;   // global intercept toggle (ON by default — safer narrow scope in content.js)
let   whitelist = [];     // sites where ZH is disabled
let   blacklist = [];     // sites where ZH is always active

// ── Storage: load settings ─────────────────────────────────────────────────
chrome.storage.local.get(["intercept","whitelist","blacklist"], r => {
  intercept = r.intercept !== false;  // default ON (user can disable in popup)
  whitelist = r.whitelist || [];
  blacklist = r.blacklist || [];
});

// React to settings changes from popup
chrome.storage.onChanged.addListener((changes) => {
  if (changes.intercept) intercept = changes.intercept.newValue !== false;
  if (changes.whitelist) whitelist = changes.whitelist.newValue || [];
  if (changes.blacklist) blacklist = changes.blacklist.newValue || [];
});

// ── Tab state ──────────────────────────────────────────────────────────────
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
    referer: details.url,
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

chrome.downloads.onCreated.addListener(async downloadItem => {
  if (!intercept) return;
  const url = downloadItem.url || downloadItem.finalUrl || "";
  if (!url || url.startsWith("blob:") || url.startsWith("data:")) return;

  // Skip non-media/file sites
  try {
    const host = new URL(url).hostname;
    if (SKIP_HOSTS.some(s => host.includes(s))) return;
  } catch { return; }

  // Only intercept actual media/file downloads
  const fname = downloadItem.filename || "";
  const isMedia = MEDIA_RE.test(url) || MEDIA_RE.test(fname);
  const isFile  = FILE_RE.test(url)  || FILE_RE.test(fname);
  if (!isMedia && !isFile) return;

  // Check whitelist
  try {
    const tabs = await chrome.tabs.query({ active:true, currentWindow:true });
    const tabUrl = tabs[0]?.url || "";
    if (whitelist.some(w => tabUrl.includes(w))) return;
  } catch {}

  // Cancel and send to app
  try {
    await chrome.downloads.cancel(downloadItem.id);
    await chrome.downloads.erase({ id: downloadItem.id });
  } catch {}

  const ok = await sendToApp(url);
  if (!ok.ok) {
    chrome.downloads.download({ url });
  }
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
    chrome.tabs.query({ active:true, currentWindow:true }, tabs => {
      if (!tabs.length) { sendResponse({ tabId:null, items:[] }); return; }
      const tab = tabs[0];
      sendResponse({
        tabId: tab.id, url: tab.url, title: tab.title,
        items: getTab(tab.id),
        intercept,
        isDisabled: whitelist.some(w => (tab.url||"").includes(w))
      });
    });
    return true;
  }

  if (msg.type === "ZH_CLEAR" && msg.tabId != null) {
    tabState.set(msg.tabId, []); updateBadge(msg.tabId);
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

async function sendToApp(url, referer, fmt, title) {
  try {
    const d = await postToApp(url, referer, fmt, title);
    if (d.ok) notify("Sent to ZH Downloader", url.slice(0,60)+"…");
    return d;
  } catch(e) {
    // App is closed → queue it, launch the app, flush when the bridge is up.
    await queuePending(url, referer);
    launchApp();
    notify("Opening ZH Downloader…", "Your download will start automatically.");
    flushWhenReady();
    return { ok:true, queued:true };
  }
}

// pending queue (survives until the app comes online)
async function queuePending(url, referer) {
  const { pending = [] } = await chrome.storage.local.get("pending");
  if (!pending.some(p => p.url === url)) pending.push({ url, referer: referer||url });
  await chrome.storage.local.set({ pending });
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
  for (let i = 0; i < 30; i++) {                 // ~60s window
    if (await pingApp()) {
      const { pending = [] } = await chrome.storage.local.get("pending");
      for (const p of pending) { try { await postToApp(p.url, p.referer); } catch {} }
      await chrome.storage.local.set({ pending: [] });
      if (pending.length) notify("ZH Downloader ready", `Sent ${pending.length} download(s).`);
      break;
    }
    await new Promise(r => setTimeout(r, 2000));
  }
  _flushing = false;
}

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
chrome.tabs.onRemoved.addListener(tabId => tabState.delete(tabId));
if (chrome.webNavigation) {
  chrome.webNavigation.onCommitted.addListener(d => {
    if (d.frameId === 0) { tabState.set(d.tabId, []); updateBadge(d.tabId); }
  });
}
