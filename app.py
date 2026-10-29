#!/usr/bin/env python3
"""Web form (no extra dependencies — Python standard library only).

  python app.py            → open http://localhost:8000
Fill in the details, upload 4–8 photos, click Generate, preview and download the MP4.
"""
import html
import os
import re
import shutil
import sys
import threading
import uuid
from email import policy
from email.parser import BytesParser
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs, unquote, urlsplit

from propvid.listing import Listing, ListingError, MAX_IMAGES
from propvid.pipeline import Options, generate
from propvid.render import FORMATS, RenderError

ROOT = os.path.dirname(os.path.abspath(__file__))
RUNS = os.path.join(ROOT, "runs")
SAMPLE = os.path.join(ROOT, "sample_data", "listing.json")
MAX_UPLOAD = 80 * 1024 * 1024  # 80 MB per request

CSS = """
*{box-sizing:border-box}body{font-family:system-ui,-apple-system,Segoe UI,sans-serif;margin:0;background:#f4f5f8;color:#1b2235}
header{background:#1b2a4a;color:#fff;padding:18px 24px}header h1{margin:0;font-size:20px}header p{margin:4px 0 0;opacity:.8;font-size:14px}
main{max-width:860px;margin:24px auto;padding:0 16px}.card{background:#fff;border-radius:12px;padding:22px;box-shadow:0 1px 3px #0002;margin-bottom:18px}
label{display:block;font-weight:600;font-size:14px;margin:12px 0 4px}input,textarea,select{width:100%;padding:9px 11px;border:1px solid #cfd4de;border-radius:8px;font:inherit}
textarea{min-height:96px}.row{display:grid;grid-template-columns:1fr 1fr;gap:14px}@media(max-width:640px){.row{grid-template-columns:1fr}}
.hint{font-size:12px;color:#667;margin-top:3px}.checks label{display:inline-flex;gap:6px;font-weight:500;margin-right:16px;align-items:center}.checks input{width:auto}
button{background:#E8632B;color:#fff;border:0;padding:12px 22px;border-radius:8px;font-size:16px;font-weight:600;cursor:pointer;margin-top:18px}
button:disabled{opacity:.6}.err{background:#fde8e8;border-left:4px solid #c62828;padding:12px 14px;border-radius:6px;white-space:pre-wrap}
.warn{background:#fff6e0;border-left:4px solid #e0a000;padding:10px 14px;border-radius:6px;font-size:14px}.warn li,.note li{margin:3px 0}
.note{font-size:13px;color:#445}video{width:100%;border-radius:10px;background:#000}a.btn{display:inline-block;background:#1b2a4a;color:#fff;padding:10px 18px;border-radius:8px;text-decoration:none;margin:12px 8px 0 0}
pre{white-space:pre-wrap;background:#f4f5f8;padding:12px;border-radius:8px;font-size:13px}
"""


def page(body: str) -> bytes:
    return (f"<!doctype html><html><head><meta charset='utf-8'><meta name='viewport' content='width=device-width,initial-scale=1'>"
            f"<title>Property Video Generator</title><style>{CSS}</style></head><body>"
            f"<header><h1>AI Property Video Generator</h1><p>Listing details + photos → ready-to-share MP4</p></header>"
            f"<main>{body}</main></body></html>").encode()


def form(values=None, error: str = "") -> bytes:
    v = values or {}
    e = lambda k: html.escape(str(v.get(k, "")), quote=True)
    feats = v.get("features", "")
    feats = "\n".join(feats) if isinstance(feats, list) else feats
    fmt_opts = "".join(f"<option value='{k}' {'selected' if v.get('format') == k else ''}>{k} {w}×{h}</option>"
                       for k, (w, h) in FORMATS.items())
    err = f"<div class='err'>{html.escape(error)}</div>" if error else ""
    return page(f"""{err}
<form class="card" method="post" action="/generate" enctype="multipart/form-data" onsubmit="this.querySelector('button').disabled=true;this.querySelector('button').textContent='Rendering… (about 30–60 s)'">
 <div class="row"><div><label>Property name *</label><input name="name" value="{e('name')}" placeholder="Skyline Residency"></div>
 <div><label>Property type</label><input name="property_type" value="{e('property_type')}" placeholder="2 BHK Apartment"></div></div>
 <div class="row"><div><label>Location</label><input name="location" value="{e('location')}" placeholder="Sector 62, Gurugram"></div>
 <div><label>Price</label><input name="price" value="{e('price')}" placeholder="₹85 Lakh"></div></div>
 <label>Key features</label><textarea name="features" placeholder="One per line (max 5 used)">{html.escape(feats)}</textarea>
 <div class="row"><div><label>Call to action</label><input name="cta" value="{e('cta')}" placeholder="Book a site visit today"></div>
 <div><label>Contact</label><input name="contact" value="{e('contact')}" placeholder="+91 98xxx xxx10 | sales@example.com"></div></div>
 <label>Property photos (4–8)</label><input type="file" name="images" accept="image/*" multiple>
 <div class="hint">JPG / PNG / WebP. Order of upload = order of scenes; the first photo is the title shot.</div>
 <label>Video format</label><select name="format">{fmt_opts}</select>
 <div class="checks" style="margin-top:14px">
  <label><input type="checkbox" name="sample" value="1">Use sample photos/details if left empty</label>
  <label><input type="checkbox" name="music" value="1" checked>Background music</label>
  <label><input type="checkbox" name="narration" value="1" checked>Narration (if TTS installed)</label>
 </div>
 <button type="submit">Generate video</button>
</form>""")


class Handler(BaseHTTPRequestHandler):
    def log_message(self, fmt, *args):
        sys.stderr.write("[web] " + fmt % args + "\n")

    def _send(self, body: bytes, status=200, ctype="text/html; charset=utf-8"):
        self.send_response(status)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):
        url = urlsplit(self.path)                       # separate "/runs/x/v.mp4" from "?dl=1"
        if url.path in ("/", "/index.html"):
            return self._send(form())
        if url.path.startswith("/runs/"):
            download = parse_qs(url.query).get("dl") == ["1"]
            return self._file(unquote(url.path[len("/runs/"):]), download)
        self._send(page("<div class='card'>Not found. <a href='/'>Back</a></div>"), 404)

    def _file(self, rel: str, download: bool = False):
        path = os.path.realpath(os.path.join(RUNS, rel))
        if not path.startswith(os.path.realpath(RUNS) + os.sep) or not os.path.isfile(path):
            return self._send(b"Not found", 404, "text/plain")
        ctype = {".mp4": "video/mp4", ".jpg": "image/jpeg", ".json": "application/json"}.get(
            os.path.splitext(path)[1], "application/octet-stream")
        size = os.path.getsize(path)
        start, end = 0, size - 1
        rng = self.headers.get("Range", "")
        m = re.match(r"bytes=(\d*)-(\d*)$", rng.strip())
        if m and (m.group(1) or m.group(2)):           # browsers stream video in byte ranges
            if m.group(1):
                start = int(m.group(1))
                end = min(int(m.group(2)), size - 1) if m.group(2) else size - 1
            else:                                       # "bytes=-N" → last N bytes
                start = max(0, size - int(m.group(2)))
            if start > end or start >= size:
                self.send_response(416)
                self.send_header("Content-Range", f"bytes */{size}")
                self.end_headers()
                return
            self.send_response(206)
            self.send_header("Content-Range", f"bytes {start}-{end}/{size}")
        else:
            self.send_response(200)
        self.send_header("Content-Type", ctype)
        self.send_header("Accept-Ranges", "bytes")
        self.send_header("Content-Length", str(end - start + 1))
        if download:
            self.send_header("Content-Disposition", f'attachment; filename="{os.path.basename(path)}"')
        self.end_headers()
        try:
            with open(path, "rb") as fh:
                fh.seek(start)
                left = end - start + 1
                while left > 0:
                    chunk = fh.read(min(256 * 1024, left))
                    if not chunk:
                        break
                    self.wfile.write(chunk)
                    left -= len(chunk)
        except (BrokenPipeError, ConnectionResetError):
            pass                                        # player stopped/seeked — normal

    def do_POST(self):
        if self.path != "/generate":
            return self._send(b"Not found", 404, "text/plain")
        length = int(self.headers.get("Content-Length") or 0)
        if length > MAX_UPLOAD:
            return self._send(form(error=f"Upload too large (max {MAX_UPLOAD // 1024 // 1024} MB). Use smaller photos."), 413)
        raw = self.rfile.read(length)
        msg = BytesParser(policy=policy.default).parsebytes(
            b"Content-Type: " + self.headers.get("Content-Type", "").encode() + b"\r\n\r\n" + raw)

        run_id = uuid.uuid4().hex[:10]
        run_dir = os.path.join(RUNS, run_id)
        os.makedirs(run_dir, exist_ok=True)
        fields, images = {}, []
        for part in (msg.iter_parts() if msg.is_multipart() else []):
            name = part.get_param("name", header="content-disposition")
            fname = part.get_filename()
            data = part.get_payload(decode=True) or b""
            if name == "images" and fname and data:
                safe = f"{len(images) + 1:02d}_" + "".join(c for c in os.path.basename(fname) if c.isalnum() or c in "._-")[-60:]
                p = os.path.join(run_dir, safe)
                with open(p, "wb") as fh:
                    fh.write(data)
                images.append(p)
            elif name:
                fields[name] = data.decode("utf-8", "replace").strip()

        if fields.get("sample") and os.path.isfile(SAMPLE):
            sample = Listing.from_json_file(SAMPLE)
            for k in ("name", "location", "price", "property_type", "cta", "contact"):
                fields[k] = fields.get(k) or getattr(sample, k)
            fields["features"] = fields.get("features") or "\n".join(sample.features)
            images = images or sample.images

        data = {**fields, "features": [f.strip() for f in fields.get("features", "").splitlines() if f.strip()],
                "images": images[:MAX_IMAGES + 4]}
        listing = Listing.from_dict(data)
        opts = Options(fmt=fields.get("format", "landscape"),
                       narration=bool(fields.get("narration")), music=bool(fields.get("music")))
        try:
            res = generate(listing, os.path.join(run_dir, "property_video.mp4"), opts)
        except (ListingError, RenderError) as exc:
            if not fields.get("sample"):
                shutil.rmtree(run_dir, ignore_errors=True)
            return self._send(form({**fields, "features": data["features"]}, error=str(exc)), 400)
        except Exception as exc:  # last-resort guard: never show a stack trace to the user
            self.log_error("Unexpected error: %r", exc)
            return self._send(form({**fields, "features": data["features"]},
                                   error=f"Unexpected error while rendering: {exc.__class__.__name__}: {exc}"), 500)

        rel = lambda p: f"/runs/{run_id}/{os.path.basename(p)}"
        warn = "".join(f"<li>{html.escape(w)}</li>" for w in res.warnings)
        notes = "".join(f"<li>{html.escape(n)}</li>" for n in res.notes)
        scenes = "\n".join(f"[{s.kind}] {s.caption}" + (f" — “{s.narration}”" if s.narration else "")
                           for s in res.script.scenes)
        body = f"""<div class="card"><video controls playsinline preload="auto" poster="{rel(res.thumbnail)}" src="{rel(res.video)}"></video>
<a class="btn" href="{rel(res.video)}?dl=1">Download MP4</a><a class="btn" href="{rel(res.script_json)}?dl=1">Script &amp; captions (JSON)</a><a class="btn" href="/">Make another</a>
<p class="note">▶ Press play to watch with sound. {res.duration:.1f}s · {len(res.script.scenes)} scenes · script source: {html.escape(res.script.source)}</p></div>
{f'<div class="card warn"><b>Heads-up</b><ul>{warn}</ul></div>' if warn else ''}
<div class="card"><b>Scenes &amp; voice-over</b><pre>{html.escape(scenes)}</pre><ul class="note">{notes}</ul></div>"""
        self._send(page(body))


def wait_for_quit() -> None:
    """Block until the user presses q. Windows: just press q. Mac/Linux: q then Enter."""
    if os.name == "nt":
        import msvcrt
        import time
        while True:
            if msvcrt.kbhit() and msvcrt.getwch().lower() == "q":
                return
            time.sleep(0.1)
    while True:
        line = sys.stdin.readline()
        if not line:                      # no keyboard attached (e.g. run in background): run forever
            threading.Event().wait()
        if line.strip().lower() == "q":
            return


def main():
    port = int(os.environ.get("PORT", sys.argv[1] if len(sys.argv) > 1 else 8000))
    os.makedirs(RUNS, exist_ok=True)
    srv = ThreadingHTTPServer(("127.0.0.1", port), Handler)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    key = "q" if os.name == "nt" else "q + Enter"
    print(f"Property Video Generator running at http://localhost:{port}")
    print(f"Press {key} to stop.")
    try:
        wait_for_quit()
    except KeyboardInterrupt:             # Ctrl+C still works as a fallback
        pass
    print("Stopping server...")
    srv.shutdown()
    srv.server_close()
    print("Stopped.")


if __name__ == "__main__":
    main()