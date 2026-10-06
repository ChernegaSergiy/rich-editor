"""Rich-editor backend: Python stdlib only.

Serves the block editor, builds Telegram Rich HTML server-side,
uploads media and calls sendRichMessage / editMessageText.
Posts are stored in SQLite with Telegram file_ids for edit reuse.
"""
import hashlib
import hmac
import http.server
import json
import mimetypes
import os
import re
import secrets
import socketserver
import sqlite3
import time
import urllib.parse
import urllib.request
from datetime import datetime, timezone

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DATA_DIR = os.environ.get("DATA_DIR", os.path.join(BASE_DIR, "..", "data"))
UPLOAD_DIR = os.path.join(DATA_DIR, "uploads")
DB_PATH = os.path.join(DATA_DIR, "rich.db")
STATIC_DIR = os.path.join(BASE_DIR, "static")

BOT_TOKEN = os.environ.get("BOT_TOKEN", "")
ADMIN_KEY = os.environ.get("ADMIN_KEY", "")
CHANNEL = os.environ.get("CHANNEL", "@nl_pe")
PORT = int(os.environ.get("PORT", "8080"))

API = "https://api.telegram.org/bot"
ALLOWED_EXT = {".png": "image/png", ".jpg": "image/jpeg",
               ".jpeg": "image/jpeg", ".webp": "image/webp", ".gif": "image/gif"}
MAX_UPLOAD = 10 * 1024 * 1024
MAX_TEXT_CHARS = 32768
MAX_MEDIA = 50
MAX_BLOCKS = 500


# ---------------------------------------------------------------- db
def db():
    os.makedirs(DATA_DIR, exist_ok=True)
    con = sqlite3.connect(DB_PATH)
    con.execute("""CREATE TABLE IF NOT EXISTS posts(
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        message_id INTEGER NOT NULL,
        chat TEXT NOT NULL,
        blocks TEXT NOT NULL,
        html TEXT NOT NULL,
        items TEXT NOT NULL,
        created_at TEXT NOT NULL)""")
    return con


# ---------------------------------------------------------------- escaping / inline markup
ESC = {"&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;"}


def esc(s):
    return re.sub(r"[&<>\"']", lambda m: ESC[m.group(0)], s)


def render_inline(text):
    """Tiny markup: **bold**, *italic*, `code`, [t](url). \\n -> <br/>."""
    out = esc(text)
    out = re.sub(r"\*\*(.+?)\*\*", r"<b>\1</b>", out)
    out = re.sub(r"(?<!\*)\*(?!\*)(.+?)(?<!\*)\*(?!\*)", r"<i>\1</i>", out)
    out = re.sub(r"`(.+?)`", r"<code>\1</code>", out)
    out = re.sub(r"\[([^\]]+)\]\((https?://[^)\s]+)\)",
                 lambda m: '<a href="%s">%s</a>' % (m.group(2), m.group(1)), out)
    return out.replace("\n", "<br/>")


def strip_tags(html_text):
    no_tags = re.sub(r"<[^>]*>", "", html_text)
    return (no_tags.replace("&amp;", "&").replace("&lt;", "<")
            .replace("&gt;", ">").replace("&quot;", '"').replace("&#39;", "'"))


# ---------------------------------------------------------------- document -> html + media
class RichError(Exception):
    pass


def build(blocks, uploads):
    """blocks: list of dicts. uploads: {upload_id: path}.
    Returns (html, media, files, items)."""
    parts = []
    media = []
    files = []   # (attach_name, path, mime)
    items = []   # for DB reuse: {"file_id"|"up": ...}
    n_media = 0
    n_blocks = 0

    def photo_ref(photo, prefix):
        nonlocal n_media
        n_media += 1
        if n_media > MAX_MEDIA:
            raise RichError("Too many media attachments (max %d)" % MAX_MEDIA)
        if "up" in photo:
            uid = photo["up"]
            if uid not in uploads:
                raise RichError("Unknown upload: %s" % uid)
            name = "%s%d_file" % (prefix, n_media)
            path = uploads[uid]
            mime = mimetypes.guess_type(path)[0] or "application/octet-stream"
            files.append((name, path, mime))
            pid = "%s%d" % (prefix, n_media)
            media.append({"id": pid,
                          "media": {"type": "photo", "media": "attach://%s" % name}})
            items.append({"up": uid, "file_id": None})
            return "tg://photo?id=%s" % pid
        if "file_id" in photo:
            pid = "%s%d" % (prefix, n_media)
            media.append({"id": pid, "media": {"type": "photo",
                                               "media": photo["file_id"]}})
            items.append({"up": None, "file_id": photo["file_id"]})
            return "tg://photo?id=%s" % pid
        raise RichError("Photo needs 'up' or 'file_id'")

    for b in blocks:
        kind = b.get("t")
        if kind == "p":
            parts.append("<p>%s</p>" % render_inline(b.get("text", "")))
            n_blocks += 1
        elif kind == "h":
            level = int(b.get("level", 2))
            if level not in (1, 2, 3, 4, 5, 6):
                raise RichError("Heading level must be 1-6")
            parts.append("<h%d>%s</h%d>" % (level, render_inline(b.get("text", "")), level))
            n_blocks += 1
        elif kind == "divider":
            parts.append("<hr/>")
            n_blocks += 1
        elif kind == "slideshow":
            photos = b.get("photos", [])
            if not photos:
                raise RichError("Slideshow has no photos")
            imgs = "".join('<img src="%s"/>' % photo_ref(ph, "p") for ph in photos)
            cap = b.get("caption", "")
            figcap = "<figcaption>%s</figcaption>" % render_inline(cap) if cap else ""
            parts.append("<tg-slideshow>%s%s</tg-slideshow>" % (imgs, figcap))
            n_blocks += 1
        else:
            raise RichError("Unknown block type: %r" % (kind,))
    if n_blocks > MAX_BLOCKS:
        raise RichError("Too many blocks (max %d)" % MAX_BLOCKS)

    html_text = "".join(parts)
    if len([*strip_tags(html_text)]) > MAX_TEXT_CHARS:
        raise RichError("Text too long (max %d chars)" % MAX_TEXT_CHARS)
    return html_text, media, files, items


# ---------------------------------------------------------------- telegram api
def tg_json(method, payload):
    req = urllib.request.Request(
        "%s%s/%s" % (API, BOT_TOKEN, method),
        data=json.dumps(payload).encode(),
        headers={"Content-Type": "application/json"}, method="POST")
    with urllib.request.urlopen(req, timeout=120) as resp:
        return json.loads(resp.read().decode())


def tg_multipart(method, fields, files):
    """fields: {name: str value}; files: [(field, path, mime)]."""
    boundary = "----rich" + secrets.token_hex(16)
    body = bytearray()

    def put(s):
        body.extend(s if isinstance(s, bytes) else s.encode())

    for name, value in fields.items():
        put("--%s\r\nContent-Disposition: form-data; name=\"%s\"\r\n\r\n%s\r\n"
            % (boundary, name, value))
    for field, path, mime in files:
        fname = os.path.basename(path)
        put("--%s\r\nContent-Disposition: form-data; name=\"%s\"; filename=\"%s\"\r\n"
            "Content-Type: %s\r\n\r\n" % (boundary, field, fname, mime))
        with open(path, "rb") as fh:
            body.extend(fh.read())
        put("\r\n")
    put("--%s--\r\n" % boundary)
    req = urllib.request.Request(
        "%s%s/%s" % (API, BOT_TOKEN, method), data=bytes(body),
        headers={"Content-Type": "multipart/form-data; boundary=%s" % boundary},
        method="POST")
    with urllib.request.urlopen(req, timeout=180) as resp:
        return json.loads(resp.read().decode())


def collect_file_ids(result, count):
    """Pick biggest PhotoSize file_id per slideshow photo, in order."""
    out = []
    try:
        for block in result.get("rich_message", {}).get("blocks", []):
            for sub in block.get("blocks", []) if block.get("type") == "slideshow" else []:
                if sub.get("type") == "photo" and sub.get("photo"):
                    out.append(sub["photo"][-1]["file_id"])
    except (KeyError, IndexError, TypeError):
        pass
    return out[:count]


# ---------------------------------------------------------------- http
class Handler(http.server.BaseHTTPRequestHandler):
    server_version = "rich-editor/1.0"

    def log_message(self, *a):
        pass

    # -- helpers
    def _send(self, code, obj, ctype="application/json"):
        data = obj if isinstance(obj, bytes) else json.dumps(obj).encode()
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def _ok(self, obj):
        self._send(200, obj)

    def _err(self, code, msg):
        self._send(code, {"ok": False, "description": msg})

    def _authed(self, query):
        key = self.headers.get("X-Auth-Key", "") or query.get("key", [""])[0]
        return bool(ADMIN_KEY) and hmac.compare_digest(key, ADMIN_KEY)

    def _body(self):
        ln = int(self.headers.get("Content-Length", "0") or 0)
        return self.rfile.read(ln) if ln else b""

    # -- multipart parser (single file field + text fields)
    def _parse_multipart(self):
        ctype = self.headers.get("Content-Type", "")
        m = re.search(r"boundary=([^;]+)", ctype)
        if not m:
            return None
        bound = ("--" + m.group(1).strip().strip('"')).encode()
        raw = self._body()
        chunks = raw.split(bound)
        fields, filedata, filename = {}, None, ""
        for ch in chunks:
            if b"Content-Disposition" not in ch:
                continue
            head, _, content = ch.partition(b"\r\n\r\n")
            content = content[: -len(b"\r\n")] if content.endswith(b"\r\n") else content
            nm = re.search(rb'name="([^"]+)"', head)
            fn = re.search(rb'filename="([^"]*)"', head)
            if not nm:
                continue
            if fn and fn.group(1):
                filename = fn.group(1).decode(errors="replace")
                filedata = content
            else:
                fields[nm.group(1).decode()] = content.decode(errors="replace")
        return fields, filedata, filename

    # -- routes
    def do_GET(self):
        url = urllib.parse.urlsplit(self.path)
        query = urllib.parse.parse_qs(url.query)
        path = url.path
        if path == "/":
            return self._serve_static("index.html", "text/html; charset=utf-8")
        if path.startswith("/static/"):
            name = os.path.basename(path)
            if name not in ("index.html",):
                return self._err(404, "Not found")
            return self._serve_static(name, "text/html; charset=utf-8")
        if not self._authed(query):
            return self._err(401, "Unauthorized")
        if path == "/api/config":
            return self._ok({"ok": True, "channel": CHANNEL,
                             "max_media": MAX_MEDIA, "max_text": MAX_TEXT_CHARS})
        if path == "/api/posts":
            con = db()
            rows = con.execute("SELECT id, message_id, chat, blocks, created_at "
                               "FROM posts ORDER BY id DESC").fetchall()
            con.close()
            posts = []
            for pid, mid, chat, blocks, created in rows:
                try:
                    bl = json.loads(blocks)
                    first = next((x.get("text", "") for x in bl
                                  if x.get("t") in ("h", "p")), "")
                except (ValueError, AttributeError):
                    first = ""
                posts.append({"id": pid, "message_id": mid, "chat": chat,
                              "excerpt": first[:120], "created_at": created,
                              "link": "https://t.me/%s/%d" % (chat.lstrip("@"), mid)})
            return self._ok({"ok": True, "posts": posts})
        m = re.match(r"^/api/posts/(\d+)$", path)
        if m:
            con = db()
            row = con.execute("SELECT id, message_id, chat, blocks, created_at "
                              "FROM posts WHERE id=?", (m.group(1),)).fetchone()
            con.close()
            if not row:
                return self._err(404, "Post not found")
            return self._ok({"ok": True, "post": {
                "id": row[0], "message_id": row[1], "chat": row[2],
                "blocks": json.loads(row[3]), "created_at": row[4]}})
        m = re.match(r"^/api/uploads/([A-Za-z0-9_-]+\.[a-z]+)$", path)
        if m:
            fpath = os.path.join(UPLOAD_DIR, m.group(1))
            if not os.path.isfile(fpath):
                return self._err(404, "Not found")
            mime = mimetypes.guess_type(fpath)[0] or "application/octet-stream"
            with open(fpath, "rb") as fh:
                return self._send(200, fh.read(), mime)
        return self._err(404, "Not found")

    def _serve_static(self, name, ctype):
        fpath = os.path.join(STATIC_DIR, name)
        if not os.path.isfile(fpath):
            return self._err(404, "Not found")
        with open(fpath, "rb") as fh:
            return self._send(200, fh.read(), ctype)

    def do_POST(self):
        url = urllib.parse.urlsplit(self.path)
        query = urllib.parse.parse_qs(url.query)
        if not self._authed(query):
            return self._err(401, "Unauthorized")
        try:
            if url.path == "/api/upload":
                return self._handle_upload()
            data = json.loads(self._body().decode() or "{}")
            if url.path == "/api/preview":
                return self._handle_preview(data)
            if url.path == "/api/send":
                return self._handle_send(data)
            if url.path == "/api/edit":
                return self._handle_edit(data)
            if url.path == "/api/delete":
                return self._handle_delete(data)
            return self._err(404, "Not found")
        except RichError as exc:
            return self._err(400, str(exc))
        except Exception as exc:  # noqa: BLE001 - report to UI
            return self._err(500, "Internal error: %s" % exc)

    # -- handlers
    def _uploads_index(self):
        os.makedirs(UPLOAD_DIR, exist_ok=True)
        return {f.rsplit(".", 1)[0]: os.path.join(UPLOAD_DIR, f)
                for f in os.listdir(UPLOAD_DIR) if "." in f}

    def _handle_upload(self):
        parsed = self._parse_multipart()
        if not parsed:
            return self._err(400, "Expected multipart body")
        _, filedata, filename = parsed
        if not filedata:
            return self._err(400, "Field 'photo' is required")
        if len(filedata) > MAX_UPLOAD:
            return self._err(400, "File too big (max 10 MB)")
        ext = os.path.splitext(filename)[1].lower()
        if ext not in ALLOWED_EXT:
            return self._err(400, "Only png/jpg/webp/gif allowed")
        uid = "u" + secrets.token_hex(8)
        with open(os.path.join(UPLOAD_DIR, uid + ext), "wb") as fh:
            fh.write(filedata)
        return self._ok({"ok": True, "upload_id": uid,
                         "preview_url": "/api/uploads/%s%s" % (uid, ext)})

    def _handle_preview(self, data):
        html_text, _, _, _ = build(data.get("blocks", []), self._uploads_index())
        return self._ok({"ok": True, "html": html_text})

    def _send_or_edit(self, method, extra, blocks):
        html_text, media, files, items = build(blocks, self._uploads_index())
        rich = {"html": html_text}
        if media:
            rich["media"] = media
        payload = dict(extra)
        payload["rich_message"] = rich
        if files:
            fields = {k: (v if isinstance(v, str) else json.dumps(v))
                      for k, v in payload.items()}
            resp = tg_multipart(method, fields, files)
        else:
            resp = tg_json(method, payload)
        if not resp.get("ok"):
            raise RichError("Telegram: %s" % resp.get("description"))
        return resp["result"], html_text, items

    def _handle_send(self, data):
        chat = data.get("chat") or CHANNEL
        result, html_text, items = self._send_or_edit(
            "sendRichMessage", {"chat_id": chat}, data.get("blocks", []))
        # resolve upload -> file_id for future edits
        fids = collect_file_ids(result, len(items))
        for it, fid in zip(items, fids):
            if fid:
                it["file_id"] = fid
        mid = result["message_id"]
        con = db()
        cur = con.execute("INSERT INTO posts(message_id, chat, blocks, html, items, created_at)"
                          " VALUES(?,?,?,?,?,?)",
                          (mid, chat, json.dumps(data.get("blocks", [])),
                           html_text, json.dumps(items),
                           datetime.now(timezone.utc).isoformat()))
        con.commit()
        pid = cur.lastrowid
        con.close()
        return self._ok({"ok": True, "message_id": mid, "post_id": pid,
                         "link": "https://t.me/%s/%d" % (chat.lstrip("@"), mid)})

    def _resolve_target(self, data):
        if data.get("post_id"):
            con = db()
            row = con.execute("SELECT message_id, chat FROM posts WHERE id=?",
                              (data["post_id"],)).fetchone()
            con.close()
            if not row:
                raise RichError("Post not found")
            return row[0], row[1]
        if data.get("message_id"):
            return int(data["message_id"]), data.get("chat") or CHANNEL
        raise RichError("post_id or message_id is required")

    def _handle_edit(self, data):
        mid, chat = self._resolve_target(data)
        blocks = data.get("blocks", [])
        # reuse stored file_ids for photos that came from this post
        if data.get("post_id"):
            con = db()
            row = con.execute("SELECT items FROM posts WHERE id=?",
                              (data["post_id"],)).fetchone()
            con.close()
            if row:
                stored = {i: json.loads(row[0])[i]
                          for i in range(len(json.loads(row[0])))}
                n = 0
                for b in blocks:
                    if b.get("t") == "slideshow":
                        for ph in b.get("photos", []):
                            if "reuse" in ph and ph["reuse"] in stored:
                                st = stored[ph["reuse"]]
                                if st.get("file_id"):
                                    ph.clear()
                                    ph["file_id"] = st["file_id"]
                            n += 1
        result, html_text, items = self._send_or_edit(
            "editMessageText", {"chat_id": chat, "message_id": mid}, blocks)
        fids = collect_file_ids(result, len(items))
        for it, fid in zip(items, fids):
            if fid and not it.get("file_id"):
                it["file_id"] = fid
        con = db()
        if data.get("post_id"):
            con.execute("UPDATE posts SET blocks=?, html=?, items=? WHERE id=?",
                        (json.dumps(blocks), html_text, json.dumps(items), data["post_id"]))
        else:
            con.execute("INSERT INTO posts(message_id, chat, blocks, html, items, created_at)"
                        " VALUES(?,?,?,?,?,?)",
                        (mid, chat, json.dumps(blocks), html_text, json.dumps(items),
                         datetime.now(timezone.utc).isoformat()))
        con.commit()
        con.close()
        return self._ok({"ok": True, "message_id": mid,
                         "link": "https://t.me/%s/%d" % (chat.lstrip("@"), mid)})

    def _handle_delete(self, data):
        mid, chat = self._resolve_target(data)
        resp = tg_json("deleteMessage", {"chat_id": chat, "message_id": mid})
        if not resp.get("ok"):
            raise RichError("Telegram: %s" % resp.get("description"))
        if data.get("post_id"):
            con = db()
            con.execute("DELETE FROM posts WHERE id=?", (data["post_id"],))
            con.commit()
            con.close()
        return self._ok({"ok": True})


def main():
    if not BOT_TOKEN or not ADMIN_KEY:
        raise SystemExit("BOT_TOKEN and ADMIN_KEY env vars are required")
    os.makedirs(UPLOAD_DIR, exist_ok=True)
    db().close()
    with socketserver.ThreadingTCPServer(("0.0.0.0", PORT), Handler) as httpd:
        httpd.allow_reuse_address = True
        print("rich-editor on 0.0.0.0:%d channel=%s" % (PORT, CHANNEL), flush=True)
        httpd.serve_forever()


if __name__ == "__main__":
    main()
