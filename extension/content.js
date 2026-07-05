(function() {
  'use strict';

  // Already injected?
  if (window.__zhLoaded) return;
  window.__zhLoaded = true;

  const VIDEO_HOSTS = ['youtube.com','youtu.be','vimeo.com','tiktok.com',
    'instagram.com','facebook.com','twitter.com','x.com','twitch.tv',
    'reddit.com','dailymotion.com','soundcloud.com','bilibili.com',
    'rumble.com','streamable.com','artgrid.io','artlist.io','pinterest.com'];

  const FILE_EXT = /\.(mp4|webm|mkv|mov|mp3|m4a|aac|wav|flac|pdf|zip|rar|7z|exe|dmg|pkg|msi|apk|iso|gz|bz2|docx?|xlsx?|pptx?|jpg|jpeg|png|gif|webp|epub)(\?|$)/i;

  const isVideoSite = VIDEO_HOSTS.some(h => location.hostname.includes(h));

  // ── shared state ──────────────────────────────────────────────────────
  const S = { items: [], btn: null, win: null, winVisible: false, dismissed: false };

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
    /* Label hidden — IDM style is icon-only circle */
    #__zhbtn .lbl { display: none !important; }
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

    #__zhwin {
      all: initial;
      position: fixed !important;
      width: 320px !important;
      z-index: 2147483647 !important;
      display: none !important;
      font-family: -apple-system, sans-serif !important;
      background: #160800 !important;
      border: 1px solid #3d1e08 !important;
      border-radius: 12px !important;
      box-shadow: 0 8px 40px rgba(0,0,0,.7) !important;
      overflow: hidden !important;
    }
    #__zhwin.open { display: block !important; }

    .__zhwin_hdr {
      display: flex !important; align-items: center !important;
      gap: 8px !important; padding: 10px 14px !important;
      background: #1c0800 !important;
      border-bottom: 1px solid #2e1005 !important;
      cursor: move !important; user-select: none !important;
    }
    .__zhwin_hdr img {
      width: 20px !important; height: 20px !important;
      border-radius: 5px !important; pointer-events: none !important;
    }
    .__zhwin_title {
      flex: 1 !important; font-size: 12px !important;
      font-weight: 600 !important; color: #ff8c42 !important;
      pointer-events: none !important;
    }
    .__zhwin_x {
      width: 16px !important; height: 16px !important;
      border-radius: 50% !important; background: #eb5757 !important;
      border: none !important; cursor: pointer !important;
      color: #fff !important; font-size: 10px !important;
      display: flex !important; align-items: center !important;
      justify-content: center !important; flex-shrink: 0 !important;
    }
    .__zhwin_body {
      padding: 8px 12px !important;
      max-height: 260px !important; overflow-y: auto !important;
    }
    .__zhwin_foot {
      padding: 8px 12px !important;
      border-top: 1px solid #2e1005 !important;
      display: flex !important; gap: 6px !important;
    }
    .__zhitem {
      background: #1e0d02 !important;
      border: 1px solid #2e1005 !important;
      border-radius: 8px !important;
      padding: 8px 10px !important; margin-bottom: 6px !important;
    }
    .__zhitem_top {
      display: flex !important; align-items: center !important;
      gap: 6px !important; margin-bottom: 4px !important;
    }
    .__zhbadge {
      font-size: 9px !important; font-weight: 700 !important;
      padding: 2px 5px !important; border-radius: 3px !important;
      flex-shrink: 0 !important;
    }
    .__zhbadge.v { background: #1a3a2a !important; color: #6fcf97 !important; }
    .__zhbadge.h { background: #2a1a3a !important; color: #bb86fc !important; }
    .__zhbadge.a { background: #1a2a3a !important; color: #56ccf2 !important; }
    .__zhbadge.f { background: #2a2a1a !important; color: #f2c94c !important; }
    .__zhname {
      font-size: 11px !important; color: #ffddc0 !important;
      white-space: nowrap !important; overflow: hidden !important;
      text-overflow: ellipsis !important; flex: 1 !important;
    }
    .__zhsz { font-size: 10px !important; color: rgba(255,140,66,.5) !important; }
    .__zhpbar {
      height: 3px !important; background: #2e1005 !important;
      border-radius: 3px !important; margin-bottom: 4px !important;
      overflow: hidden !important;
    }
    .__zhpfill {
      height: 100% !important;
      background: linear-gradient(90deg,#ff6b35,#ffaa55) !important;
      border-radius: 3px !important; transition: width .3s !important;
    }
    .__zhst {
      font-size: 10px !important; color: rgba(255,140,66,.4) !important;
      margin-bottom: 4px !important;
    }
    .__zhacts { display: flex !important; gap: 5px !important; }
    .__zhbtn_dl, .__zhbtn_cp {
      flex: 1 !important; padding: 6px 8px !important;
      border-radius: 6px !important; border: none !important;
      font-size: 12px !important; font-weight: 600 !important;
      cursor: pointer !important;
    }
    .__zhbtn_dl {
      background: #ff6b35 !important; color: #fff !important;
    }
    .__zhbtn_cp {
      background: #2e1005 !important; color: #ff8c42 !important;
      border: 1px solid #3d1e08 !important;
    }
    .__zhfoot_btn {
      flex: 1 !important; padding: 7px !important;
      border-radius: 7px !important; border: none !important;
      font-size: 12px !important; font-weight: 600 !important;
      cursor: pointer !important;
    }
    .__zhfoot_btn.p { background: #ff6b35 !important; color: #fff !important; }
    .__zhfoot_btn.g {
      background: #1e0d02 !important; color: #ff8c42 !important;
      border: 1px solid #3d1e08 !important;
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
  document.head.appendChild(style);

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
  function fmtSize(b) {
    if (!b) return '';
    if (b > 1073741824) return (b/1073741824).toFixed(1)+' GB';
    if (b > 1048576)    return (b/1048576).toFixed(1)+' MB';
    if (b > 1024)       return (b/1024).toFixed(0)+' KB';
    return b+'B';
  }
  function badgeCls(t) {
    if (['HLS','DASH','STREAM'].includes(t)) return 'h';
    if (['MP4','WEBM','VIDEO','MKV'].includes(t)) return 'v';
    if (t === 'AUDIO') return 'a';
    return 'f';
  }
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
  function addItem(item) {
    if (S.items.some(function(i) { return i.url === item.url; })) return false;
    S.items.unshift(item);
    if (S.items.length > 40) S.items.length = 40;
    renderItems();
    updateBtnLabel();
    return true;
  }

  function updateBtnLabel() {
    var lbl = document.querySelector('#__zhbtn .lbl');
    if (lbl) lbl.textContent = S.items.length > 0
      ? 'Download (' + S.items.length + ')'
      : 'Download';
  }

  function renderItems() {
    var body = document.querySelector('#__zhwin .__zhwin_body');
    if (!body) return;
    if (!S.items.length) {
      body.innerHTML = '<div style="text-align:center;color:rgba(255,140,66,.35);font-size:12px;padding:20px 0">No media detected yet.<br>Play a video or visit a page with files.</div>';
      return;
    }
    body.innerHTML = S.items.map(function(it, i) {
      return '<div class="__zhitem">' +
        '<div class="__zhitem_top">' +
          '<span class="__zhbadge ' + badgeCls(it.type) + '">' + it.type + '</span>' +
          '<span class="__zhname" title="' + it.url + '">' + (it.name || shortUrl(it.url)) + '</span>' +
          '<span class="__zhsz">' + (it.size || '') + '</span>' +
        '</div>' +
        '<div class="__zhpbar"><div class="__zhpfill" style="width:' + (it.pct||0) + '%"></div></div>' +
        '<div class="__zhst">' + (it.status || 'Ready') + '</div>' +
        '<div class="__zhacts">' +
          '<button class="__zhbtn_dl" data-idx="' + i + '">Download</button>' +
          '<button class="__zhbtn_cp" data-idx="' + i + '">Copy URL</button>' +
        '</div>' +
      '</div>';
    }).join('');

    // Attach click handlers
    body.querySelectorAll('.__zhbtn_dl').forEach(function(btn) {
      btn.addEventListener('click', function() { dlItem(parseInt(btn.dataset.idx)); });
    });
    body.querySelectorAll('.__zhbtn_cp').forEach(function(btn) {
      btn.addEventListener('click', function() { cpItem(parseInt(btn.dataset.idx)); });
    });
  }

  function dlItem(i) {
    var it = S.items[i];
    if (!it) return;
    // blob: URLs are internal — use page URL instead
    var sendUrl = it.url;
    if (sendUrl.startsWith('blob:') || sendUrl.startsWith('data:')) {
      sendUrl = location.href;
    }
    S.items[i].status = 'Sending...';
    renderItems();
    chrome.runtime.sendMessage(
      { type: 'ZH_SEND_TO_APP', url: sendUrl, referer: location.href },
      function(res) {
        if (res && res.ok) {
          S.items[i].status = 'Sent! Downloading...';
          renderItems();
          toast('Sent to ZH Downloader!');
        } else {
          S.items[i].status = 'Ready';
          renderItems();
          toast('Open ZH Downloader app first!', 'err');
        }
      }
    );
  }

  function cpItem(i) {
    var it = S.items[i];
    if (!it) return;
    try {
      navigator.clipboard.writeText(it.url).then(function() { toast('URL copied!'); });
    } catch(e) {
      var t = document.createElement('textarea');
      t.value = it.url;
      document.body.appendChild(t);
      t.select();
      document.execCommand('copy');
      t.remove();
      toast('URL copied!');
    }
  }

  // ── Mini window ───────────────────────────────────────────────────────
  function buildWin() {
    if (S.win) return;
    var div = document.createElement('div');
    div.id = '__zhwin';
    div.innerHTML =
      '<div class="__zhwin_hdr" id="__zhwin_hdr">' +
        '<img src="' + iconUrl('icon48.png') + '" alt="">' +
        '<span class="__zhwin_title">ZH Downloader</span>' +
        '<button class="__zhwin_x" id="__zhwin_x">x</button>' +
      '</div>' +
      '<div class="__zhwin_body"></div>' +
      '<div class="__zhwin_foot">' +
        '<button class="__zhfoot_btn g" id="__zhwin_hide">Hide</button>' +
        '<button class="__zhfoot_btn p" id="__zhwin_page">Download Page</button>' +
      '</div>';
    document.body.appendChild(div);
    S.win = div;

    document.getElementById('__zhwin_x').addEventListener('click', function() {
      hideWin();
    });
    document.getElementById('__zhwin_hide').addEventListener('click', function() {
      hideWin();
    });
    document.getElementById('__zhwin_page').addEventListener('click', function() {
      chrome.runtime.sendMessage(
        { type: 'ZH_SEND_TO_APP', url: location.href },
        function(res) {
          toast(res && res.ok ? 'Sent page to app!' : 'Open ZH Downloader app first!',
                res && res.ok ? 'ok' : 'err');
        }
      );
    });

    // Drag header
    var hdr = document.getElementById('__zhwin_hdr');
    var dragging = false, ox = 0, oy = 0, ol = 0, ot = 0;
    hdr.addEventListener('mousedown', function(e) {
      if (e.target.id === '__zhwin_x') return;
      dragging = true;
      ox = e.clientX; oy = e.clientY;
      var r = div.getBoundingClientRect();
      ol = r.left; ot = r.top;
      div.style.right = 'auto'; div.style.bottom = 'auto';
      div.style.left = ol + 'px'; div.style.top = ot + 'px';
      e.preventDefault();
    });
    document.addEventListener('mousemove', function(e) {
      if (!dragging) return;
      div.style.left = (ol + e.clientX - ox) + 'px';
      div.style.top  = (ot + e.clientY - oy) + 'px';
    });
    document.addEventListener('mouseup', function() { dragging = false; });

    renderItems();
  }

  function showWin() {
    buildWin();
    // Position above float button
    if (S.btn) {
      var r = S.btn.getBoundingClientRect();
      var ww = 320, wh = 320;
      var left = Math.max(4, r.right - ww);
      var top  = r.top - wh - 8;
      if (top < 4) top = r.bottom + 8;
      S.win.style.right  = 'auto';
      S.win.style.bottom = 'auto';
      S.win.style.left   = left + 'px';
      S.win.style.top    = top  + 'px';
    }
    S.win.classList.add('open');
    S.winVisible = true;
    renderItems();
  }

  function hideWin() {
    if (S.win) S.win.classList.remove('open');
    S.winVisible = false;
  }

  function toggleWin() {
    // One click = direct download of current page
    var sendUrl = location.href;
    chrome.runtime.sendMessage(
      { type: 'ZH_SEND_TO_APP', url: sendUrl, referer: sendUrl },
      function(res) {
        if (res && res.ok) {
          toast('Sent to ZH Downloader!');
        } else {
          toast('Open ZH Downloader app first!', 'err');
        }
      }
    );
  }

  // ── Floating button ───────────────────────────────────────────────────
  function buildBtn() {
    if (S.btn) return;
    // Respect user-dismissed state (cleared on tab close)
    if (S.dismissed) return;
    var btn = document.createElement('div');
    btn.id = '__zhbtn';
    btn.innerHTML =
      '<div class="wrap">' +
        '<img class="icon" src="' + iconUrl('icon48.png') + '" alt="">' +
        '<span class="lbl">Download</span>' +
        '<span class="close" title="Hide on this tab">×</span>' +
      '</div>';
    document.body.appendChild(btn);
    S.btn = btn;

    // Close button → dismiss for this tab
    var closeEl = btn.querySelector('.close');
    if (closeEl) {
      closeEl.addEventListener('click', function(e) {
        e.stopPropagation(); e.preventDefault();
        S.dismissed = true;
        btn.remove();
        S.btn = null;
      });
      closeEl.addEventListener('mousedown', function(e) { e.stopPropagation(); });
    }

    // Drag + click
    var dragging = false, moved = false;
    var startX = 0, startY = 0, origLeft = 0, origTop = 0;

    btn.addEventListener('mousedown', function(e) {
      if (e.button !== 0) return;
      dragging = true;
      moved    = false;
      startX   = e.clientX;
      startY   = e.clientY;
      var r    = btn.getBoundingClientRect();
      origLeft = r.left;
      origTop  = r.top;
      btn.style.right  = 'auto';
      btn.style.bottom = 'auto';
      btn.style.left   = origLeft + 'px';
      btn.style.top    = origTop  + 'px';
      e.preventDefault();
    });

    document.addEventListener('mousemove', function(e) {
      if (!dragging) return;
      var dx = e.clientX - startX;
      var dy = e.clientY - startY;
      if (Math.abs(dx) > 4 || Math.abs(dy) > 4) moved = true;
      if (moved) {
        btn.style.left = (origLeft + dx) + 'px';
        btn.style.top  = (origTop  + dy) + 'px';
      }
    });

    document.addEventListener('mouseup', function(e) {
      if (!dragging) return;
      var wasMoved = moved;
      dragging = false;
      moved    = false;
      if (!wasMoved) toggleWin();
    });
  }

  function initBtn() {
    if (document.body) buildBtn();
    else document.addEventListener('DOMContentLoaded', buildBtn);
  }

  // Watchdog: re-add button every 2s if missing from DOM.
  // Respects S.dismissed → user closed it, don't re-create until tab reload.
  function ensureBtnAlive() {
    if (!isVideoSite) return;
    if (S.dismissed) return;
    // On YouTube, only on watch pages
    if (location.hostname.includes('youtube.com') && location.pathname !== '/watch') {
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

  if (isVideoSite) initBtn();
  setInterval(ensureBtnAlive, 2000);

  // ── Background messages ───────────────────────────────────────────────
  chrome.runtime.onMessage.addListener(function(msg) {
    if (msg.type !== 'ZH_UPDATED') return;
    var added = 0;
    (msg.items || []).forEach(function(it) {
      if (addItem({
        url:     it.url,
        type:    it.type,
        name:    it.name || shortUrl(it.url),
        size:    it.sizeStr || '',
        referer: it.referer || location.href,
        pct:     0,
        status:  'Ready',
      })) added++;
    });
    if (added > 0 && !S.btn) initBtn();
  });

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
                  size:'', referer:location.href, pct:0, status:'Ready' });
        seen[s] = true;
      });
    });
    // For video sites — always add page URL as downloadable item
    if (isVideoSite && !seen[location.href]) {
      addItem({ url:location.href, type:'VIDEO', name:document.title.slice(0,60),
                size:'', referer:location.href, pct:0, status:'Ready' });
      seen[location.href] = true;
    }
    document.querySelectorAll('a[href]').forEach(function(a) {
      if (a.href && FILE_EXT.test(a.href) && !seen[a.href]) {
        addItem({ url:a.href, type:'FILE',
                  name:(a.textContent||'').trim().slice(0,40)||shortUrl(a.href),
                  size:'', referer:location.href, pct:0, status:'Ready' });
        seen[a.href] = true;
      }
    });
  }

  scan();
  var scanTimer;
  new MutationObserver(function() {
    clearTimeout(scanTimer);
    scanTimer = setTimeout(scan, 1000);
  }).observe(document.body || document.documentElement, { childList:true, subtree:true });
  document.addEventListener('visibilitychange', function() {
    if (!document.hidden) scan();
  });

  // ── Download link intercept ───────────────────────────────────────────
  // ONLY intercept explicit <a download> links — not all file URLs.
  // Disabled entirely when S.dismissed (user closed floating button).
  // This prevents extension from hijacking normal browser navigation.
  document.addEventListener('click', function(e) {
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
  }, true);

})();


// ── IDM-style video overlay ─────────────────────────────────────────────
// Hover any playing <video> → a "⬇ Download ▾" pill floats at its top-right.
// Click = send page URL (video sites need yt-dlp on the PAGE url, not the blob).
// ▾ = quality menu (4K / 1080p / MP3). Sent to the app bridge with a fmt hint.
(function () {
  if (window.top !== window.self) return;           // main frame only
  var PILL_ID = "__zhvid_pill";
  var MENU_ID = "__zhvid_menu";
  var css = document.createElement("style");
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
    var s = (v.currentSrc || v.src || "");
    // blob/MSE (YouTube, FB, most sites) → the PAGE url is what yt-dlp needs
    if (!s || s.indexOf("blob:") === 0 || s.indexOf("data:") === 0) return location.href;
    return s.indexOf("http") === 0 ? location.href : location.href;   // page URL is the reliable choice everywhere
  }

  function markSent() {
    pill.querySelector(".zhp_main").textContent = "\u2713 Sent";
    setTimeout(function () { pill.querySelector(".zhp_main").textContent = "\u2b07 Download"; hidePill(); }, 1200);
  }
  function pickSniffed(items) {
    // Prefer a real stream the extension sniffed from network (Artlist/Artgrid/HLS/mp4) —
    // this is how IDM catches sites where the <video> is a blob. Fall back to page URL.
    if (!items || !items.length) return null;
    var score = function (it) {
      var u = (it.url || "").toLowerCase(), t = (it.type || "").toLowerCase();
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
  function sendCurrent(fmt) {
    if (!curVid) return;
    if (!extAlive()) {
      alert("ZH Downloader was updated — refresh this page (Cmd+R) once, then click Download again.");
      return;
    }
    try {
      chrome.runtime.sendMessage({ type: "ZH_GET_TAB" }, function (resp) {
        var sn = pickSniffed(resp && resp.items);
        var url = sn ? sn.url : videoUrlFor(curVid);
        var ref = location.href;
        chrome.runtime.sendMessage({ type: "ZH_SEND_TO_APP", url: url, referer: ref, fmt: fmt || "", title: cleanTitle() });
        markSent();
      });
    } catch (e) {
      try { chrome.runtime.sendMessage({ type: "ZH_SEND_TO_APP", url: videoUrlFor(curVid), referer: location.href, fmt: fmt || "", title: cleanTitle() }); markSent(); } catch (e2) {}
    }
  }

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
  document.addEventListener("mouseover", function (e) {
    if (!onVideoPage()) { hidePill(); return; }
    var v = e.target && e.target.tagName === "VIDEO" ? e.target :
            (e.target.querySelector ? null : null);
    if (!v) {
      // player containers cover the <video>; find one under the pointer
      var els = document.elementsFromPoint(e.clientX, e.clientY);
      for (var i = 0; i < els.length; i++) {
        if (els[i].tagName === "VIDEO") { v = els[i]; break; }
      }
    }
    if (v) { curVid = v; clearTimeout(hideT); placePill(v); }
    else if (e.target !== pill && !pill.contains(e.target) &&
             e.target !== menu && !menu.contains(e.target)) schedHide();
  }, true);

  window.addEventListener("scroll", function () { if (curVid && pill.style.display !== "none") placePill(curVid); }, true);
  window.addEventListener("resize", function () { if (curVid && pill.style.display !== "none") placePill(curVid); });

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
  document.addEventListener("click", function () { hideMenu(); });
})();
