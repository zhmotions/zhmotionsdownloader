// pickSniffed scoring — which sniffed stream the extension hands to the app.
//
// A Pinterest pin came down at 540w because `<hash>_540w.m3u8` (one fixed, low
// rendition) scored the same as the master `<hash>.m3u8`, so whichever the
// browser requested first won. The master must always outrank a variant.
//
//   node tests/sniff_score_test.js [path/to/content.js]

const fs = require('fs');
const path = require('path');
const src = fs.readFileSync(process.argv[2] ||
  path.join(__dirname, '..', 'extension', 'content.js'), 'utf8');

// pull the self-contained function out of the content script (it touches no DOM)
const start = src.indexOf('function pickSniffed');
const after = src.indexOf('\n  }', start);
if (start < 0 || after < 0) { console.error('pickSniffed not found'); process.exit(1); }
const pickSniffed = eval('(' + src.slice(start, after + 4) + ')');

let fails = 0, passes = 0;
const eq = (label, got, want) => {
  const ok = JSON.stringify(got) === JSON.stringify(want);
  ok ? passes++ : fails++;
  console.log((ok ? 'PASS  ' : 'FAIL  ') + label + ' = ' + JSON.stringify(got) +
              (ok ? '' : '  (want ' + JSON.stringify(want) + ')'));
};
const u = (url) => ({ url, type: '' });
const pick = (...urls) => (pickSniffed(urls.map(u)) || {}).url || null;

const H = 'https://v1.pinimg.com/videos/iht/hls/23/65/73/abc123abc123';

// ── the bug ──────────────────────────────────────────────────────────────
eq('master beats a Pinterest variant, variant seen first',
   pick(H + '_540w.m3u8', H + '.m3u8'), H + '.m3u8');
eq('master beats a Pinterest variant, master seen first',
   pick(H + '.m3u8', H + '_720w.m3u8'), H + '.m3u8');
eq('a lone variant is still better than nothing',
   pick(H + '_540w.m3u8'), H + '_540w.m3u8');

// ── existing behaviour that must not regress ─────────────────────────────
eq('extractor CDNs are never picked (page URL handles them)',
   pick('https://video.twimg.com/x/mp4a/128000/y.m3u8'), null);
eq('a named master still wins',
   pick('https://cdn.artlist.io/a/720p/x.m3u8', 'https://cdn.artlist.io/a/master.m3u8'),
   'https://cdn.artlist.io/a/master.m3u8');
eq('HLS beats a progressive mp4',
   pick('https://x/y.mp4', 'https://x/y.m3u8'), 'https://x/y.m3u8');
eq('mp4 beats audio-only',
   pick('https://x/y.m4a', 'https://x/y.mp4'), 'https://x/y.mp4');
eq('nothing sniffed → null', pick(), null);


// ── Facebook: the reel FEED is not a video ───────────────────────────────
// /reel/?s=tab carries no id; the old check just looked for the word "reel",
// so the feed URL was sent as-is and yt-dlp answered "Unsupported URL".
const fbStart = src.indexOf('function isFbVideoPage');
const fbEnd = src.indexOf('\n  }', fbStart);
const isFbVideoPage = eval('(' + src.slice(fbStart, fbEnd + 4) + ')');
[['/reel/?s=tab', false],
 ['/reel/1650134176280128', true],
 ['/watch/?v=1416358443875238', true],
 ['/videos/1234567890', true],
 ['/share/v/abc123/', true],
 ['/', false],
 ['/watch/', false],
 ['/marketplace/item/99', false],
].forEach(([u, want]) => eq('isFbVideoPage ' + u, isFbVideoPage(u), want));
console.log();
console.log((fails ? fails + ' FAILED, ' : '') + passes + ' passed');
process.exit(fails ? 1 : 0);
