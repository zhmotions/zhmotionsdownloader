(function() {
  'use strict';

  // ── Re-injection guard ────────────────────────────────────────────────
  // background.js reinjectAllTabs() re-runs this file in tabs that may already
  // have a copy, and Chrome's own document_end injection can race it. Three
  // cases have to behave differently:
  //   live copy   → bail out, or every document-level listener gets doubled
  //                 (that is how one Download click turned into two sends)
  //   stale copy  → the extension was updated, so the old copy's chrome.* calls
  //                 all throw. Tear its UI + listeners down, then re-init so the
  //                 tab heals without a manual Cmd+R.
  //   fresh tab   → normal init.
  if (window.__zhLoaded) {
    var _live = false;
    try { _live = !!(window.__zhAlive && window.__zhAlive()); } catch (e) { _live = false; }
    if (_live) { window.__zhSkip = true; return; }
    try { window.__zhTeardown && window.__zhTeardown(); } catch (e) {}
  }
  window.__zhLoaded = true;
  window.__zhSkip   = false;   // read by the overlay-pill IIFE at the bottom
  window.__zhAlive  = function() {
    try { return !!(chrome && chrome.runtime && chrome.runtime.id); } catch (e) { return false; }
  };

  const VIDEO_HOSTS = ['youtube.com','youtu.be','vimeo.com','tiktok.com',
    'instagram.com','facebook.com','twitter.com','x.com','twitch.tv',
    'reddit.com','dailymotion.com','soundcloud.com','bilibili.com',
    'rumble.com','streamable.com','artgrid.io','artlist.io','pinterest.com'];

  const FILE_EXT = /\.(mp4|webm|mkv|mov|mp3|m4a|aac|wav|flac|pdf|zip|rar|7z|exe|dmg|pkg|msi|apk|iso|gz|bz2|docx?|xlsx?|pptx?|jpg|jpeg|png|gif|webp|epub)(\?|$)/i;

  const isVideoSite = VIDEO_HOSTS.some(h => location.hostname.includes(h));

  // ── shared state ──────────────────────────────────────────────────────
  // dismissed survives a re-init (extension update) — the user closed the
  // circle on this tab and shouldn't have it pop back after an auto-update.
  const S = { items: [], btn: null, dismissed: !!window.__zhDismissed };

  // ── CSS ───────────────────────────────────────────────────────────────
  const style = document.createElement('style');
  style.id = '__zh_style';
  style.textContent = `
    /* IDM-style compact circle. Fixed 52x52 px. Icon only. No stretch. */
    #__zhbtn {
      all: initial;
      position: fixed !important;
      bottom: 80px !important;
      right: 20px !important;
      width: 52px !important;
      height: 52px !important;
      z-index: 2147483647 !important;
      cursor: grab !important;
      font-family: -apple-system, sans-serif !important;
    }
    #__zhbtn:active { cursor: grabbing !important; }
    #__zhbtn .wrap {
      display: flex !important;
      align-items: center !important;
      justify-content: center !important;
      width: 52px !important;
      height: 52px !important;
      box-sizing: border-box !important;
      background: #1c0800 !important;
      border: 2px solid #ff6b35 !important;
      border-radius: 50% !important;
      box-shadow: 0 4px 18px rgba(255,80,20,.55) !important;
      transition: transform 0.15s ease, box-shadow 0.15s ease !important;
      pointer-events: none !important;
    }
    #__zhbtn:hover .wrap {
      transform: scale(1.08) !important;
      box-shadow: 0 6px 24px rgba(255,80,20,.75) !important;
    }
    #__zhbtn .icon {
      width: 28px !important; height: 28px !important;
      border-radius: 6px !important;
      pointer-events: none !important;
    }
    /* Close × in top-right corner of circle */
    #__zhbtn .close {
      pointer-events: auto !important;
      position: absolute !important;
      top: -4px !important; right: -4px !important;
      display: flex !important; align-items: center !important; justify-content: center !important;
      width: 18px !important; height: 18px !important;
      background: #2a0e00 !important;
      color: #ff8c42 !important;
      font-size: 12px !important; font-weight: 700 !important;
      border-radius: 50% !important;
      border: 1.5px solid #ff6b35 !important;
      cursor: pointer !important;
      user-select: none !important; line-height: 1 !important;
      opacity: 0 !important;
      transition: opacity 0.15s ease !important;
    }
    #__zhbtn:hover .close { opacity: 1 !important; }
    #__zhbtn .close:hover {
      background: #eb5757 !important; color: #fff !important; border-color: #eb5757 !important;
    }

    #__zhtoast {
      position: fixed !important; z-index: 2147483647 !important;
      top: 16px !important; left: 50% !important;
      transform: translateX(-50%) !important;
      padding: 9px 18px !important; border-radius: 8px !important;
      font-family: -apple-system, sans-serif !important;
      font-size: 13px !important; font-weight: 500 !important;
      box-shadow: 0 4px 20px rgba(0,0,0,.5) !important;
      display: none !important; white-space: nowrap !important;
      pointer-events: none !important;
    }
    #__zhtoast.ok  { background:#1a2e1a !important; color:#6fcf97 !important; border:1px solid #6fcf97 !important; }
    #__zhtoast.err { background:#2e1a1a !important; color:#eb5757 !important; border:1px solid #eb5757 !important; }
  `;
  (document.head || document.documentElement).appendChild(style);

  // ── Toast ─────────────────────────────────────────────────────────────
  let toastTimer;
  function toast(msg, type) {
    let el = document.getElementById('__zhtoast');
    if (!el) {
      el = document.createElement('div');
      el.id = '__zhtoast';
      document.body.appendChild(el);
    }
    el.textContent = msg;
    el.className = type === 'err' ? 'err' : 'ok';
    el.style.display = 'block';
    clearTimeout(toastTimer);
    toastTimer = setTimeout(function() { el.style.display = 'none'; }, 2800);
  }

  // ── Helpers ───────────────────────────────────────────────────────────
  function shortUrl(url) {
    try {
      var p = decodeURIComponent(new URL(url).pathname.split('/').filter(Boolean).pop() || '');
      return (p || url).slice(0, 40);
    } catch(e) { return url.slice(0, 40); }
  }
  function iconUrl(name) {
    return chrome.runtime.getURL('icons/' + name);
  }

  // ── Items ─────────────────────────────────────────────────────────────
  // Kept only to decide whether this page has anything worth showing the
  // circle for. The old in-page list window that rendered them was never
  // reachable (nothing called showWin) — it has been removed.
  function addItem(item) {
    if (S.items.some(function(i) { return i.url === item.url; })) return false;
    S.items.unshift(item);
    if (S.items.length > 40) S.items.length = 40;
    return true;
  }

  // ── Send ──────────────────────────────────────────────────────────────
  // One click on the circle = download what this page is showing. It routes
  // through the overlay pill's sender so both entry points behave identically:
  // the circle used to post a bare page URL with no title, which is
  // "ERROR: Unsupported URL" on Artlist/Artgrid and a UUID filename elsewhere.
  function sendPage() {
    if (typeof window.__zhSendCurrent === 'function') {
      window.__zhSendCurrent('', null, function(res) {
        if (res && res.blocked) { toast('Play the clip for a second first', 'err'); return; }
        toast(res && res.ok ? 'Sent to ZH Downloader!' : 'Open ZH Downloader app first!',
              res && res.ok ? 'ok' : 'err');
      });
      return;
    }
    chrome.runtime.sendMessage(
      { type: 'ZH_SEND_TO_APP', url: location.href, referer: location.href },
      function(res) {
        toast(res && res.ok ? 'Sent to ZH Downloader!' : 'Open ZH Downloader app first!',
              res && res.ok ? 'ok' : 'err');
      }
    );
  }

  // ── Floating button ───────────────────────────────────────────────────
  // Drag state + the document-level listeners live out here on purpose. They
  // used to be created inside buildBtn(), which the 2s watchdog calls again
  // every time the button is re-added (SPA nav) — each pass leaked another
  // mousemove + mouseup listener onto document.
  var drag = { on:false, moved:false, sx:0, sy:0, ox:0, oy:0 };

  function onDocMove(e) {
    if (!drag.on || !S.btn) return;
    var dx = e.clientX - drag.sx, dy = e.clientY - drag.sy;
    if (Math.abs(dx) > 4 || Math.abs(dy) > 4) drag.moved = true;
    if (drag.moved) {
      S.btn.style.left = (drag.ox + dx) + 'px';
      S.btn.style.top  = (drag.oy + dy) + 'px';
    }
  }
  function onDocUp() {
    if (!drag.on) return;
    var wasMoved = drag.moved;
    drag.on = false; drag.moved = false;
    if (!wasMoved) sendPage();
  }
  document.addEventListener('mousemove', onDocMove);
  document.addEventListener('mouseup', onDocUp);

  function buildBtn() {
    if (S.btn) return;
    // Respect user-dismissed state (cleared on tab close)
    if (S.dismissed) return;
    var btn = document.createElement('div');
    btn.id = '__zhbtn';
    btn.innerHTML =
      '<div class="wrap">' +
        '<img class="icon" src="' + iconUrl('icon48.png') + '" alt="">' +
        '<span class="close" title="Hide on this tab">×</span>' +
      '</div>';
    document.body.appendChild(btn);
    S.btn = btn;

    // Close button → dismiss for this tab (hides the overlay pill too — they
    // used to disagree, so × left the pill floating over videos)
    var closeEl = btn.querySelector('.close');
    if (closeEl) {
      closeEl.addEventListener('click', function(e) {
        e.stopPropagation(); e.preventDefault();
        S.dismissed = true;
        window.__zhDismissed = true;
        try { window.__zhHidePill && window.__zhHidePill(); } catch (err) {}
        btn.remove();
        S.btn = null;
      });
      closeEl.addEventListener('mousedown', function(e) { e.stopPropagation(); });
    }

    btn.addEventListener('mousedown', function(e) {
      if (e.button !== 0) return;
      var r = btn.getBoundingClientRect();
      drag.on = true; drag.moved = false;
      drag.sx = e.clientX; drag.sy = e.clientY;
      drag.ox = r.left;    drag.oy = r.top;
      btn.style.right  = 'auto';
      btn.style.bottom = 'auto';
      btn.style.left   = r.left + 'px';
      btn.style.top    = r.top  + 'px';
      e.preventDefault();
    });
  }

  function initBtn() {
    if (document.body) buildBtn();
    else document.addEventListener('DOMContentLoaded', buildBtn);
  }

  // Watchdog: re-add button every 2s if missing from DOM.
  // Respects S.dismissed → user closed it, don't re-create until tab reload.
  function ensureBtnAlive() {
    if (S.dismissed) return;
    // On YouTube, only on watch/shorts pages (shorts used to lose the button
    // even though the overlay pill still offered itself there)
    if (location.hostname.includes('youtube.com') &&
        location.pathname !== '/watch' && location.pathname.indexOf('/shorts/') !== 0) {
      var existing = document.getElementById('__zhbtn');
      if (existing) existing.remove();
      S.btn = null;
      return;
    }
    if (!document.getElementById('__zhbtn')) {
      S.btn = null;
      initBtn();
    }
  }

  var btnTimer = null;
  if (isVideoSite) {
    initBtn();
    btnTimer = setInterval(ensureBtnAlive, 2000);   // only ticks on video sites now
  }

  // ── Background messages ───────────────────────────────────────────────
  function onBgMessage(msg) {
    if (!msg || msg.type !== 'ZH_UPDATED') return;
    var added = 0;
    (msg.items || []).forEach(function(it) {
      if (addItem({
        url:     it.url,
        type:    it.type,
        name:    it.name || shortUrl(it.url),
        size:    it.sizeStr || '',
        referer: it.referer || location.href,
      })) added++;
    });
    if (added > 0 && !S.btn) initBtn();
  }
  chrome.runtime.onMessage.addListener(onBgMessage);

  // ── DOM scan ──────────────────────────────────────────────────────────
  function scan() {
    var seen = {};
    S.items.forEach(function(i) { seen[i.url] = true; });
    document.querySelectorAll('video,audio').forEach(function(el) {
      [el.src, el.currentSrc].concat(
        Array.from(el.querySelectorAll('source')).map(function(s) { return s.src; })
      ).filter(function(s) {
        // Skip blob/data URLs — use page URL for video sites
        return s && !seen[s] && !s.startsWith('blob:') && !s.startsWith('data:');
      }).forEach(function(s) {
        addItem({ url:s, type:'VIDEO', name:document.title.slice(0,40),
                  size:'', referer:location.href });
        seen[s] = true;
      });
    });
    // For video sites — always add page URL as downloadable item
    if (isVideoSite && !seen[location.href]) {
      addItem({ url:location.href, type:'VIDEO', name:document.title.slice(0,60),
                size:'', referer:location.href });
      seen[location.href] = true;
    }
    // Feed pages carry thousands of anchors and this runs on every mutation
    // burst — cap the walk so scrolling YouTube/Facebook stays smooth.
    var links = document.querySelectorAll('a[href]');
    var lim = Math.min(links.length, 500);
    for (var i = 0; i < lim; i++) {
      var a = links[i];
      if (a.href && FILE_EXT.test(a.href) && !seen[a.href]) {
        addItem({ url:a.href, type:'FILE',
                  name:(a.textContent||'').trim().slice(0,40)||shortUrl(a.href),
                  size:'', referer:location.href });
        seen[a.href] = true;
      }
    }
  }

  scan();
  var scanTimer;
  var mo = new MutationObserver(function() {
    clearTimeout(scanTimer);
    scanTimer = setTimeout(scan, 1000);
  });
  mo.observe(document.body || document.documentElement, { childList:true, subtree:true });
  function onVis() { if (!document.hidden) scan(); }
  document.addEventListener('visibilitychange', onVis);

  // ── Download link intercept ───────────────────────────────────────────
  // ONLY intercept explicit <a download> links — not all file URLs.
  // Disabled entirely when S.dismissed (user closed floating button).
  // This prevents extension from hijacking normal browser navigation.
  function onDocClick(e) {
    if (S.dismissed) return;
    var el = e.target;
    while (el && el !== document) {
      if (el.tagName === 'A' && el.href) {
        // Only intercept links with explicit 'download' attribute.
        // Browsing to .pdf/.zip URL should NOT be hijacked.
        if (el.hasAttribute('download')) {
          e.preventDefault();
          e.stopPropagation();
          // Direct send to app — no popup panel
          chrome.runtime.sendMessage(
            { type: 'ZH_SEND_TO_APP', url: el.href, referer: location.href },
            function(res) {
              if (res && res.ok) toast('Sent to ZH Downloader!');
              else toast('Open ZH Downloader app first!', 'err');
            }
          );
          return;
        }
      }
      el = el.parentElement;
    }
  }
  document.addEventListener('click', onDocClick, true);

  // ── Teardown ──────────────────────────────────────────────────────────
  // Called by the NEXT injection of this file when it finds this copy stale
  // (extension updated). Everything here is plain DOM/timer work — no chrome.*
  // call — so it still runs after the extension context is invalidated.
  window.__zhTeardown = function() {
    try { if (btnTimer) clearInterval(btnTimer); } catch (e) {}
    try { clearTimeout(scanTimer); clearTimeout(toastTimer); } catch (e) {}
    try { mo.disconnect(); } catch (e) {}
    try {
      document.removeEventListener('mousemove', onDocMove);
      document.removeEventListener('mouseup', onDocUp);
      document.removeEventListener('click', onDocClick, true);
      document.removeEventListener('visibilitychange', onVis);
    } catch (e) {}
    try { chrome.runtime.onMessage.removeListener(onBgMessage); } catch (e) {}
    ['__zh_style','__zhbtn','__zhtoast'].forEach(function(id) {
      var el = document.getElementById(id);
      if (el && el.remove) el.remove();
    });
    S.btn = null;
  };

})();


// ── IDM-style video overlay ─────────────────────────────────────────────
// Hover any playing <video> → a "⬇ Download ▾" pill floats at its top-right.
// Click = send page URL (video sites need yt-dlp on the PAGE url, not the blob).
// ▾ = quality menu (4K / 1080p / MP3). Sent to the app bridge with a fmt hint.
(function () {
  if (window.top !== window.self) return;           // main frame only
  // Same re-injection story as the top of this file. This block had NO guard,
  // so a re-inject built a SECOND pill with a second set of listeners and one
  // click sent the download twice. __zhSkip is set by the block above.
  if (window.__zhSkip) return;
  try { window.__zhPillTeardown && window.__zhPillTeardown(); } catch (e) {}

  var PILL_ID = "__zhvid_pill";
  var MENU_ID = "__zhvid_menu";
  var CSS_ID  = "__zhvid_css";
  var css = document.createElement("style");
  css.id = CSS_ID;
  css.textContent =
    "#" + PILL_ID + "{position:fixed!important;z-index:2147483647!important;display:none;" +
    "align-items:center;gap:0;background:#d4a017!important;color:#0a0606!important;" +
    "border-radius:8px!important;font:600 12px -apple-system,sans-serif!important;" +
    "box-shadow:0 2px 10px rgba(0,0,0,.45)!important;overflow:hidden!important;cursor:pointer!important;}" +
    "#" + PILL_ID + " .zhp_main{padding:7px 10px!important;white-space:nowrap!important;}" +
    "#" + PILL_ID + " .zhp_more{padding:7px 8px!important;border-left:1px solid rgba(0,0,0,.25)!important;}" +
    "#" + PILL_ID + " .zhp_main:hover,#" + PILL_ID + " .zhp_more:hover{background:#e8b52e!important;}" +
    "#" + MENU_ID + "{position:fixed!important;z-index:2147483647!important;display:none;" +
    "background:#1c1520!important;border:1px solid #3a3340!important;border-radius:8px!important;" +
    "box-shadow:0 4px 18px rgba(0,0,0,.5)!important;overflow:hidden!important;min-width:150px!important;}" +
    "#" + MENU_ID + " div{padding:8px 14px!important;color:#eee!important;" +
    "font:500 12px -apple-system,sans-serif!important;cursor:pointer!important;}" +
    "#" + MENU_ID + " div:hover{background:#d4a017!important;color:#0a0606!important;}";
  document.documentElement.appendChild(css);

  var pill = document.createElement("div");
  pill.id = PILL_ID;
  pill.innerHTML = '<span class="zhp_main">⬇ Download</span><span class="zhp_more">▾</span>';
  document.documentElement.appendChild(pill);

  var menu = document.createElement("div");
  menu.id = MENU_ID;
  var OPTS = [["4k", "4K (2160p)"], ["hd", "HD (1080p)"], ["mp3", "Audio MP3"]];
  OPTS.forEach(function (o) {
    var d = document.createElement("div");
    d.textContent = o[1];
    d.addEventListener("click", function (e) {
      e.stopPropagation(); hideMenu(); sendCurrent(o[0]);
    });
    menu.appendChild(d);
  });
  document.documentElement.appendChild(menu);

  var curVid = null, hideT = null;

  function videoUrlFor(v) {
    // On feed/search/list pages the page URL is a LIST — yt-dlp can't extract
    // from it ("Unsupported URL" on X, "playlist: 0 items" on YouTube). The
    // hovered <video> sits inside a card that links the REAL watch page —
    // walk up from the video and use that link instead of location.href.
    function walkUp(el, sel) {
      for (var i = 0; el && i < 14; i++) {
        var a = (el.querySelector && el.querySelector(sel)) ||
                (el.closest && el.matches && el.matches(sel) ? el : null);
        if (!a && el.closest) a = el.closest(sel);
        if (a && a.getAttribute("href")) return new URL(a.getAttribute("href"), location.origin).href;
        el = el.parentElement;
      }
      return "";
    }
    try {
      var host = location.hostname;
      if (host.includes("youtube.com") && location.pathname !== "/watch" && v) {
        var yu = walkUp(v, 'a[href*="/watch?v="], a[href^="/shorts/"]');
        if (yu) return yu;
      }
      // X/Twitter: only /status/ URLs are downloadable. On search/home/profile
      // feeds, the tweet card links its own /status/ page (the timestamp link).
      if ((host === "x.com" || host.endsWith("twitter.com")) && location.pathname.indexOf("/status/") < 0 && v) {
        var xu = walkUp(v, 'a[href*="/status/"]');
        if (xu) return xu.split("?")[0];
      }
      // Facebook feeds: the card links the real /watch?v= | /videos/ | /reel/.
      if (host.includes("facebook.com") && v &&
          !(/\/videos\/|\/reel|\/watch\/?\?v=|\/share\/v\//.test(location.pathname + location.search))) {
        var fu = walkUp(v, 'a[href*="/videos/"], a[href*="/reel/"], a[href*="/watch/?v="], a[href*="/watch?v="], a[href*="/share/v/"]');
        if (fu) return fu;
      }
    } catch (e) {}
    // blob/MSE (YouTube, FB, most sites) → the PAGE url is what yt-dlp needs
    return location.href;
  }

  function markSent(msg) {
    pill.querySelector(".zhp_main").textContent = msg || "✓ Sent";
    setTimeout(function () { pill.querySelector(".zhp_main").textContent = "⬇ Download"; hidePill(); }, 1400);
  }
  function pickSniffed(items) {
    // Prefer a real stream the extension sniffed from network (Artlist/Artgrid/HLS/mp4) —
    // this is how IDM catches sites where the <video> is a blob. Fall back to page URL.
    if (!items || !items.length) return null;
    var score = function (it) {
      var u = (it.url || "").toLowerCase(), t = (it.type || "").toLowerCase();
      if (/video\.twimg\.com|fbcdn\.net|googlevideo\.com/.test(u)) return 0; // extractor sites' CDNs — page URL handles these
      // HLS master playlist beats a variant playlist: the master holds ALL
      // renditions so the app can pick the highest (HD/4K/8K); a variant with a
      // res/bitrate token is a single quality — often the low autoplay preview.
      var isHls = u.indexOf(".m3u8") >= 0 || t === "hls";
      if (isHls && /(master|playlist|index)\.m3u8/.test(u)) return 6;
      if (isHls && !/(\d{3,4}p|\/(360|480|540|720|1080|1440|2160)\/|_(360|480|540|720)_)/.test(u)) return 5;
      if (isHls) return 4;
      if (u.indexOf(".mpd") >= 0) return 3;
      if (/\.(mp4|mkv|mov|webm|m4v)(\?|$)/.test(u)) return 2;
      if (/\.(mp3|m4a|aac|wav|flac)(\?|$)/.test(u)) return 1;
      return 0;
    };
    var best = null, bs = 0;
    items.forEach(function (it) { var s = score(it); if (s > bs) { bs = s; best = it; } });
    return bs > 0 ? best : null;
  }
  // Page title, minus the trailing " - YouTube" / " | Pinterest" site suffix —
  // names sniffed raw streams (Artlist/Pinterest m3u8) that have no metadata title.
  function cleanTitle() {
    try {
      var t = (document.title || "").trim();
      t = t.replace(/\s*[-|–—•·]\s*(YouTube|Pinterest|Artlist|Artgrid|Vimeo|Facebook|Instagram|TikTok|X|Twitter|Dailymotion)\b.*$/i, "");
      return t.replace(/\s+/g, " ").trim().slice(0, 80);
    } catch (e) { return ""; }
  }
  // After the extension is reloaded/updated, an already-injected content script
  // is orphaned: every chrome.* call throws. Detect it and tell the user to
  // refresh instead of silently doing nothing.
  function extAlive() {
    try { return !!(chrome && chrome.runtime && chrome.runtime.id); }
    catch (e) { return false; }
  }
  // fmt: "" | "4k" | "hd" | "mp3".  vid: optional <video> (the circle button
  // passes null — there is nothing hovered).  cb: optional, gets the bridge
  // reply, plus {blocked:true} when we refuse to send a URL yt-dlp can't use.
  function sendCurrent(fmt, vid, cb) {
    var v = vid || curVid;
    if (!extAlive()) {
      alert("ZH Downloader was updated — refresh this page (Cmd+R) once, then click Download again.");
      if (cb) cb({ ok: false });
      return;
    }
    try {
      chrome.runtime.sendMessage({ type: "ZH_GET_TAB" }, function (resp) {
        // Sniffed streams ONLY where yt-dlp has no extractor (Artlist/Artgrid/
        // Pinterest). On X/Facebook/YouTube etc the sniffer catches variant
        // playlists (e.g. video.twimg.com .../mp4a/128000/... = AUDIO-only)
        // and downloads went wrong — the page URL is what yt-dlp needs there.
        var SNIFF_FIRST   = /(artlist\.io|artgrid\.io|pinterest\.)/i.test(location.hostname);
        var NO_EXTRACTOR  = /(artlist\.io|artgrid\.io)/i.test(location.hostname);
        var sn = SNIFF_FIRST ? pickSniffed(resp && resp.items) : null;
        // Artlist/Artgrid have no yt-dlp extractor at all, so a page-URL
        // fallback is guaranteed "ERROR: Unsupported URL". Say what's wrong
        // instead of sending junk — the usual cause is that the clip hasn't
        // played yet (nothing sniffed) or the service worker slept.
        if (!sn && NO_EXTRACTOR) {
          markSent("▶ Play clip first");
          if (cb) cb({ ok: false, blocked: true });
          return;
        }
        var url = sn ? sn.url : videoUrlFor(v);
        var ref = location.href;
        chrome.runtime.sendMessage({ type: "ZH_SEND_TO_APP", url: url, referer: ref, fmt: fmt || "", title: cleanTitle() }, function (r) {
          // Real ACK from the app: duplicate → tell the user instead of a blind "Sent"
          markSent(r && r.status === "duplicate" ? "✓ Already added" : "✓ Sent");
          if (cb) cb(r || { ok: false });
        });
      });
    } catch (e) {
      try {
        chrome.runtime.sendMessage({ type: "ZH_SEND_TO_APP", url: videoUrlFor(v), referer: location.href, fmt: fmt || "", title: cleanTitle() }, function (r) { if (cb) cb(r || { ok: false }); });
        markSent();
      } catch (e2) { if (cb) cb({ ok: false }); }
    }
  }
  // The circle button in the block above sends through this, so both entry
  // points get the same SNIFF_FIRST handling and title.
  window.__zhSendCurrent = sendCurrent;
  window.__zhHidePill    = function () { try { hidePill(); } catch (e) {} };

  function placePill(v) {
    var r = v.getBoundingClientRect();
    if (r.width < 220 || r.height < 120) { hidePill(); return; }   // skip thumbnails/tiny players
    pill.style.display = "flex";
    var top = Math.max(8, r.top + 10);
    var left = Math.min(window.innerWidth - pill.offsetWidth - 8, r.right - pill.offsetWidth - 10);
    pill.style.top = top + "px";
    pill.style.left = Math.max(8, left) + "px";
  }

  function hidePill() { pill.style.display = "none"; hideMenu(); }
  function hideMenu() { menu.style.display = "none"; }

  function schedHide() {
    clearTimeout(hideT);
    hideT = setTimeout(function () {
      if (!pill.matches(":hover") && !menu.matches(":hover") &&
          !(curVid && curVid.matches && curVid.matches(":hover"))) hidePill();
    }, 600);
  }

  // On watch-page-style sites, only offer the pill on an actual video page.
  // Feed/home pages autoplay hover-PREVIEWS in <video> tags; the pill would
  // send the HOMEPAGE url and the app would download the wrong thing.
  function onVideoPage() {
    var h = location.hostname, p = location.pathname;
    if (h.includes("youtube.com"))  return p === "/watch" || p.startsWith("/shorts/");
    if (h.includes("facebook.com")) return /\/(watch|reel|videos)\b/.test(p) || location.search.indexOf("v=") >= 0;
    if (h.includes("twitter.com") || h === "x.com" || h.endsWith(".x.com")) return p.indexOf("/status/") >= 0;
    if (h.includes("pinterest."))   return p.indexOf("/pin/") >= 0;
    if (h.includes("instagram.com")) return /\/(reel|reels|p|tv)\//.test(p);
    if (h.includes("tiktok.com"))   return p.indexOf("/video/") >= 0 || p.indexOf("/photo/") >= 0;
    // Stock grids hover-play previews of MANY clips — only offer the pill on a
    // single clip's page, where the sniffed stream is unambiguous.
    if (h.includes("artgrid.io"))   return p.indexOf("/clip/") >= 0;
    if (h.includes("artlist.io"))   return /\/(clip|song)\//.test(p);
    return true;   // other sites: no feed-preview pattern — allow everywhere
  }
  function onMouseOver(e) {
    if (window.__zhDismissed) { hidePill(); return; }   // user closed the circle → stay out of the way
    var v = e.target && e.target.tagName === "VIDEO" ? e.target : null;
    if (!v) {
      // player containers cover the <video>; find one under the pointer
      var els = document.elementsFromPoint(e.clientX, e.clientY);
      for (var i = 0; i < els.length; i++) {
        if (els[i].tagName === "VIDEO") { v = els[i]; break; }
      }
    }
    // Feed/search pages: only offer the pill when we can resolve the hovered
    // preview to a real video URL (videoUrlFor walks up to the /watch link) —
    // otherwise the LIST page url would be sent ("playlist: 0 items" junk).
    if (!onVideoPage() && !(v && videoUrlFor(v) !== location.href)) { hidePill(); return; }
    if (v) { curVid = v; clearTimeout(hideT); placePill(v); }
    else if (e.target !== pill && !pill.contains(e.target) &&
             e.target !== menu && !menu.contains(e.target)) schedHide();
  }
  document.addEventListener("mouseover", onMouseOver, true);

  function onScroll() { if (curVid && pill.style.display !== "none") placePill(curVid); }
  function onResize() { if (curVid && pill.style.display !== "none") placePill(curVid); }
  window.addEventListener("scroll", onScroll, true);
  window.addEventListener("resize", onResize);

  pill.querySelector(".zhp_main").addEventListener("click", function (e) {
    e.stopPropagation(); sendCurrent("");            // app's current default quality
  });
  pill.querySelector(".zhp_more").addEventListener("click", function (e) {
    e.stopPropagation();
    var r = pill.getBoundingClientRect();
    menu.style.top = (r.bottom + 6) + "px";
    menu.style.left = Math.max(8, r.right - 150) + "px";
    menu.style.display = "block";
  });
  function onDocClickPill() { hideMenu(); }
  document.addEventListener("click", onDocClickPill);

  // Same contract as __zhTeardown above: DOM/timer only, safe to run after the
  // extension context is invalidated.
  window.__zhPillTeardown = function () {
    try { clearTimeout(hideT); } catch (e) {}
    try {
      document.removeEventListener("mouseover", onMouseOver, true);
      document.removeEventListener("click", onDocClickPill);
      window.removeEventListener("scroll", onScroll, true);
      window.removeEventListener("resize", onResize);
    } catch (e) {}
    [PILL_ID, MENU_ID, CSS_ID].forEach(function (id) {
      var el = document.getElementById(id);
      if (el && el.remove) el.remove();
    });
    curVid = null;
  };
})();
