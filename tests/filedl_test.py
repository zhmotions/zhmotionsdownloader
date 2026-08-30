"""FileDL against a local server: ranges, resume, truncation, bad names.

The file downloader is what handles everything yt-dlp doesn't (zips, PDFs,
installers, direct media). Its failures are quiet — a short part used to be
concatenated into the final file and reported as done — so these tests drive it
against a server that can misbehave on purpose.

    python3 tests/filedl_test.py
"""
import hashlib
import http.server
import importlib.util
import pathlib
import socketserver
import sys
import tempfile
import threading

ROOT = pathlib.Path(__file__).resolve().parent.parent
SRC  = pathlib.Path(sys.argv[1]) if len(sys.argv) > 1 else ROOT / "zh_downloader.py"
spec = importlib.util.spec_from_file_location("zhd", SRC)
zhd  = importlib.util.module_from_spec(spec); sys.modules["zhd"] = zhd
spec.loader.exec_module(zhd)

fails = passes = 0


def eq(label, got, want):
    global fails, passes
    ok = got == want
    passes += ok; fails += not ok
    print(("PASS  " if ok else "FAIL  ") + label + " = " + repr(got) +
          ("" if ok else "  (want " + repr(want) + ")"))


BODY = bytes(range(256)) * 400          # 102,400 deterministic bytes
DIGEST = hashlib.md5(BODY).hexdigest()
MODE = {"ranges": True, "truncate_first": False, "ignore_range": False,
        "disposition": None}


class Handler(http.server.BaseHTTPRequestHandler):
    def log_message(self, *a): pass

    def _send(self, body, status=200, extra=None):
        self.send_response(status)
        self.send_header("Content-Length", str(len(body)))
        if MODE["ranges"]: self.send_header("Accept-Ranges", "bytes")
        if MODE["disposition"]:
            self.send_header("Content-Disposition", MODE["disposition"])
        for k, v in (extra or {}).items(): self.send_header(k, v)
        self.end_headers()
        if self.command != "HEAD": self.wfile.write(body)

    def do_HEAD(self): self._send(BODY)

    def do_GET(self):
        rng = self.headers.get("Range")
        if not rng or MODE["ignore_range"]:
            return self._send(BODY)
        s, _, e = rng.split("=")[1].partition("-")
        s = int(s); e = int(e) if e else len(BODY) - 1
        chunk = BODY[s:e + 1]
        if MODE["truncate_first"]:
            MODE["truncate_first"] = False
            chunk = chunk[:len(chunk) // 2]          # hang up early, once
        self._send(chunk, 206, {"Content-Range": "bytes %d-%d/%d" % (s, e, len(BODY))})


srv = socketserver.TCPServer(("127.0.0.1", 0), Handler)
srv.allow_reuse_address = True
threading.Thread(target=srv.serve_forever, daemon=True).start()
URL = "http://127.0.0.1:%d/pack.zip" % srv.server_address[1]


def fetch(**mode):
    MODE.update({"ranges": True, "truncate_first": False, "ignore_range": False,
                 "disposition": None})
    MODE.update(mode)
    dest = pathlib.Path(tempfile.mkdtemp())
    dl = zhd.FileDL(URL, dest, n=4, log_cb=lambda m: None)
    out = dl.run()
    return pathlib.Path(out), dl


p, dl = fetch()
eq("multi-part download is byte-exact", hashlib.md5(p.read_bytes()).hexdigest(), DIGEST)
eq("…and named from the URL", p.name, "pack.zip")
eq("…with the real size", dl._total, len(BODY))

p, _ = fetch(truncate_first=True)
eq("a short range is retried, not concatenated short",
   hashlib.md5(p.read_bytes()).hexdigest(), DIGEST)

p, _ = fetch(ranges=False)
eq("no range support → single stream, still exact",
   hashlib.md5(p.read_bytes()).hexdigest(), DIGEST)

p, _ = fetch(disposition='attachment; filename="Real Name.zip"')
eq("server filename wins", p.name, "Real Name.zip")

p, _ = fetch(disposition="attachment; filename*=UTF-8''caf%C3%A9%20pack.zip")
eq("RFC 5987 name is decoded", p.name, "café pack.zip")

p, _ = fetch(disposition='attachment; filename="../../escape.zip"')
eq("a traversal name is defanged", p.name, "escape.zip")

# resume: half a file already on disk, server honours the range
dest = pathlib.Path(tempfile.mkdtemp())
half = dest / "pack.zip"; half.write_bytes(BODY[:len(BODY)//2])
MODE.update({"ranges": False, "truncate_first": False, "ignore_range": False,
             "disposition": None})
dl = zhd.FileDL(URL, dest, n=1, log_cb=lambda m: None)
out = pathlib.Path(dl.run())
eq("resume completes the file", hashlib.md5(out.read_bytes()).hexdigest(), DIGEST)

# and a server that ignores the range must not be appended twice
dest = pathlib.Path(tempfile.mkdtemp())
half = dest / "pack.zip"; half.write_bytes(BODY[:len(BODY)//2])
MODE.update({"ranges": False, "ignore_range": True})
dl = zhd.FileDL(URL, dest, n=1, log_cb=lambda m: None)
out = pathlib.Path(dl.run())
eq("ignored range restarts instead of doubling the file",
   hashlib.md5(out.read_bytes()).hexdigest(), DIGEST)

srv.shutdown()
print()
print(("%d FAILED, " % fails if fails else "") + "%d passed" % passes)
sys.exit(1 if fails else 0)
