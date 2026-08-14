// background.js logic tests — runs the real service-worker file inside a vm
// with a stubbed chrome API. No browser needed.
//   node bg.test.js [path/to/background.js]
const fs = require("fs");
const vm = require("vm");
const path = require("path");

const BG = process.argv[2] || path.join(__dirname, "background.js");
const src = fs.readFileSync(BG, "utf8");

let fails = 0, passes = 0;
function eq(label, got, want) {
  const ok = JSON.stringify(got) === JSON.stringify(want);
  ok ? passes++ : fails++;
  console.log((ok ? "PASS  " : "FAIL  ") + label + " = " + JSON.stringify(got) +
              (ok ? "" : "  (want " + JSON.stringify(want) + ")"));
}

function makeCtx(opts = {}) {
  const rec = {
    listeners: {}, notifications: [], browserDownloads: [], posted: [],
    local: JSON.parse(JSON.stringify(opts.local || {})),
    session: JSON.parse(JSON.stringify(opts.session || {})),
    pingOk: opts.pingOk === true,
  };
  const on = name => ({ addListener: fn => { (rec.listeners[name] = rec.listeners[name] || []).push(fn); } });
  const area = store => ({
    get(keys, cb) {
      const out = {};
      const list = keys == null ? Object.keys(store) : (typeof keys === "string" ? [keys] : keys);
      for (const k of list) if (k in store) out[k] = store[k];
      if (cb) { cb(out); return; }
      return Promise.resolve(out);
    },
    set(obj, cb) { Object.assign(store, JSON.parse(JSON.stringify(obj))); if (cb) cb(); return Promise.resolve(); },
  });

  const chrome = {
    runtime: { onMessage: on("msg"), onStartup: on("startup"), onInstalled: on("installed"),
               sendMessage: () => Promise.resolve() },
    storage: { local: area(rec.local), session: area(rec.session), onChanged: on("changed") },
    webRequest: { onResponseStarted: { addListener: fn => { rec.listeners.req = [fn]; } } },
    webNavigation: { onCommitted: on("nav"), onHistoryStateUpdated: on("navSpa") },
    downloads: { onCreated: on("dl"), cancel: () => Promise.resolve(), erase: () => Promise.resolve(),
                 download: o => { rec.browserDownloads.push(o.url); return Promise.resolve(1); } },
    tabs: { onRemoved: on("tabGone"),
            // both call styles: the old file used the callback form
            query: (q, cb) => { const t = [{ id: 7, url: "https://artlist.io/clip/1", title: "clip" }];
                                if (cb) { cb(t); return; } return Promise.resolve(t); },
            create: () => {}, remove: () => {} },
    action: { setBadgeBackgroundColor: () => {}, setBadgeText: () => {} },
    contextMenus: { create: () => {}, update: () => {}, onClicked: on("menu") },
    notifications: { create: o => rec.notifications.push(o.title) },
  };

  const ctx = {
    chrome, console, JSON, Date, Math, Object, Promise, URL, parseInt, String, Error, AbortSignal,
    setTimeout: fn => { fn(); return 0; },        // instant timers: 30 x 2s flush loop runs at once
    clearTimeout: () => {},
    fetch: async (url) => {
      if (!rec.pingOk) throw new Error("offline");
      if (!url.endsWith("/ping")) rec.posted.push(url);
      return { json: async () => ({ ok: true, status: "queued" }) };
    },
  };
  ctx.globalThis = ctx;
  vm.createContext(ctx);
  vm.runInContext(src, ctx, { filename: "background.js" });
  return { ctx, rec };
}

// ask background.js the same question the overlay pill asks
function zhGetTab(ctx) {
  return new Promise(res => ctx.chrome.runtime.onMessage &&
    rechandlers(ctx).forEach(h => h({ type: "ZH_GET_TAB" }, {}, res)));
}
const _handlers = new WeakMap();
function rechandlers(ctx) { return _handlers.get(ctx) || []; }

(async () => {
  // ── 1. STREAM_KW no longer swallows every manifest/preview/stream word ────
  {
    const { ctx } = makeCtx();
    const w = ctx.isWanted;
    eq("noise: /static/manifest.json ignored", w("https://site.com/static/manifest.json", "application/json", ""), false);
    eq("noise: /stream/config.txt ignored",    w("https://site.com/stream/config.txt", "text/plain", ""), false);
    eq("noise: ?preview=1 page ignored",       w("https://site.com/page?preview=1", "text/html", ""), false);
    eq("real: artlist master.m3u8 kept",       w("https://cdn.artlist.io/a/master.m3u8", "application/x-mpegURL", ""), true);
    eq("real: index.m3u8 kept",                w("https://cdn.x.com/v/index.m3u8", "", ""), true);
    eq("real: .mpd kept",                      w("https://cdn.x.com/v/stream.mpd", "", ""), true);
    eq("real: extensionless HLS via ctype",    w("https://cdn.x.com/v/abc123", "application/x-mpegURL", ""), true);
    eq("real: plain mp4 kept",                 w("https://cdn.x.com/v/clip.mp4", "video/mp4", ""), true);
  }

  // ── 2. sniffed streams survive a service-worker restart ──────────────────
  {
    const { ctx, rec } = makeCtx();
    _handlers.set(ctx, rec.listeners.msg || []);
    ctx.push(7, { url: "https://cdn.artlist.io/a/master.m3u8", type: "HLS", name: "a" });
    // the very first persist waits for the restore to settle before publishing
    await new Promise(r => setTimeout(r, 0));
    eq("session mirror written", Object.keys(rec.session.tabState || {}), ["7"]);

    // worker dies; only storage.session survives
    const boot = makeCtx({ session: rec.session });
    _handlers.set(boot.ctx, boot.rec.listeners.msg || []);
    const resp = await zhGetTab(boot.ctx);
    eq("after worker restart: streams restored", (resp.items || []).length, 1);
    eq("after worker restart: correct url", (resp.items || [])[0] && resp.items[0].url,
       "https://cdn.artlist.io/a/master.m3u8");

    // A webRequest that wakes the worker lands BEFORE the session read resolves.
    // push() therefore creates the bucket first; the restore must merge into it,
    // not skip the tab, and must not publish its half-empty map over the saved one.
    const race = makeCtx({ session: rec.session });
    _handlers.set(race.ctx, race.rec.listeners.msg || []);
    race.ctx.push(7, { url: "https://cdn.artlist.io/b/fresh.m3u8", type: "HLS", name: "b" });
    const merged = await zhGetTab(race.ctx);
    eq("race: freshly sniffed stream kept", (merged.items || []).map(i => i.url).includes(
       "https://cdn.artlist.io/b/fresh.m3u8"), true);
    eq("race: previously saved stream NOT lost", (merged.items || []).map(i => i.url).includes(
       "https://cdn.artlist.io/a/master.m3u8"), true);
    await new Promise(r => setTimeout(r, 0));
    eq("race: session still holds both", (race.rec.session.tabState["7"] || []).length, 2);

    // same restart on the OLD in-memory-only design would report nothing
    const cold = makeCtx();
    _handlers.set(cold.ctx, cold.rec.listeners.msg || []);
    const empty = await zhGetTab(cold.ctx);
    eq("control: cold worker with no session data", (empty.items || []).length, 0);
  }

  // ── 3. pending queue expires (no more surprise downloads days later) ─────
  {
    const old = Date.now() - 7 * 60 * 60 * 1000;   // 7h ago, TTL is 6h
    const { ctx, rec } = makeCtx({ local: { pending: [
      { url: "https://old.example/a.mp4", referer: "", src: "", ts: old },
      { url: "https://new.example/b.mp4", referer: "", src: "", ts: Date.now() },
    ] } });
    await ctx.queuePending("https://third.example/c.mp4", "", "intercept");
    eq("stale entry dropped", rec.local.pending.map(p => p.url),
       ["https://new.example/b.mp4", "https://third.example/c.mp4"]);
    eq("new entry stamped + tagged",
       [typeof rec.local.pending[1].ts, rec.local.pending[1].src], ["number", "intercept"]);
  }

  // ── 4. app never starts → cancelled browser downloads are handed back ────
  {
    const { ctx, rec } = makeCtx({ pingOk: false, local: { pending: [
      { url: "https://site/file.zip",  referer: "", src: "intercept", ts: Date.now() },
      { url: "https://site/live.m3u8", referer: "", src: "",          ts: Date.now() },
    ] } });
    await ctx.flushWhenReady();
    eq("intercepted download returned to browser", rec.browserDownloads, ["https://site/file.zip"]);
    eq("stream send stays queued for the app", rec.local.pending.map(p => p.url), ["https://site/live.m3u8"]);
    eq("user is told", rec.notifications, ["ZH Downloader didn't start"]);
  }

  // ── 5. app comes up → queue flushes and empties ──────────────────────────
  {
    const { ctx, rec } = makeCtx({ pingOk: true, local: { pending: [
      { url: "https://site/file.zip", referer: "", src: "intercept", ts: Date.now() },
    ] } });
    await ctx.flushWhenReady();
    eq("queued item posted to the app", rec.posted.length, 1);
    eq("queue emptied", rec.local.pending, []);
    eq("nothing dumped on the browser", rec.browserDownloads, []);
  }

  console.log("\n" + (fails ? fails + " FAILED, " : "") + passes + " passed");
  process.exit(fails ? 1 : 0);
})();
