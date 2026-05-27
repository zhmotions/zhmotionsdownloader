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
    #__zhbtn {
      all: initial;
      position: fixed !important;
      bottom: 80px !important;
      right: 20px !important;
      z-index: 2147483647 !important;
      cursor: pointer !important;
      font-family: -apple-system, sans-serif !important;
    }
    #__zhbtn .wrap {
      display: flex !important;
      align-items: center !important;
      gap: 8px !important;
      background: #1c0800 !important;
      border: 1.5px solid #ff6b35 !important;
      border-radius: 50px !important;
      padding: 8px 14px 8px 10px !important;
      box-shadow: 0 4px 20px rgba(255,80,20,.45) !important;
      pointer-events: none !important;
    }
    #__zhbtn:hover .wrap {
      box-shadow: 0 6px 28px rgba(255,80,20,.65) !important;
    }
    #__zhbtn .icon {
      width: 24px !important; height: 24px !important;
      border-radius: 6px !important; flex-shrink: 0 !important;
    }
    #__zhbtn .lbl {
      font-size: 13px !important; font-weight: 600 !important;
      color: #ff8c42 !important; white-space: nowrap !important;
      user-select: none !important;
    }
    #__zhbtn .close {
      pointer-events: auto !important;
      display: inline-flex !important; align-items: center !important; justify-content: center !important;
      width: 20px !important; height: 20px !important;
      margin-left: 6px !important;
      background: rgba(255,255,255,0.1) !important;
      color: #ff8c42 !important; font-size: 16px !important; font-weight: 700 !important;
      border-radius: 50% !important; cursor: pointer !important;
      user-select: none !important; line-height: 1 !important;
    }
    #__zhbtn .close:hover {
      background: rgba(235,87,87,0.9) !important; color: #fff !important;
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
