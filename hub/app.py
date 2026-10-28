"""Stego Hub: a small private server for a closed group.

The server handles logins, stores/relays opaque encrypted blobs ("drops") and
relays encrypted chat messages. All encryption/decryption and steganography
happens in the browser with a passphrase the server never sees (end-to-end).

Config (environment variables):
  ADMIN_USER / ADMIN_PASSWORD  bootstrap admin account (created if missing)
  DATA_DIR                     where hub.db lives (default ./data)
  MAX_UPLOAD_MB                max drop size (default 25)
  DROP_TTL_DAYS                drops older than this are purged (default 14)
"""

import asyncio
import hashlib
import hmac
import json
import os
import re
import secrets
import sqlite3
import time
from contextlib import contextmanager
from pathlib import Path
from urllib.parse import unquote, urlparse

from fastapi import Depends, FastAPI, HTTPException, Request, Response, WebSocket, WebSocketDisconnect
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

BASE = Path(__file__).parent
DATA_DIR = Path(os.environ.get("DATA_DIR", BASE / "data"))
DATA_DIR.mkdir(parents=True, exist_ok=True)
DB_PATH = DATA_DIR / "hub.db"
MAX_UPLOAD = int(float(os.environ.get("MAX_UPLOAD_MB", "25")) * 1024 * 1024)
DROP_TTL = int(float(os.environ.get("DROP_TTL_DAYS", "14")) * 86400)
SESSION_TTL = 7 * 86400
MAX_DROPS_PER_USER = 100
HISTORY = 100
MAX_CHAT_CT = 16 * 1024

USER_RE = re.compile(r"^[a-z0-9_.-]{2,24}$")
ROOM_RE = re.compile(r"^[a-z0-9_-]{1,32}$")
KINDS = {"text", "img-msg", "aud-msg", "aud-img", "file"}

app = FastAPI(docs_url=None, redoc_url=None, openapi_url=None)


# --------------------------------------------------------------------------
# Database
# --------------------------------------------------------------------------

@contextmanager
def db():
    con = sqlite3.connect(DB_PATH, timeout=10)
    con.row_factory = sqlite3.Row
    try:
        yield con
        con.commit()
    finally:
        con.close()


def init_db():
    with db() as con:
        con.executescript("""
        PRAGMA journal_mode=WAL;
        CREATE TABLE IF NOT EXISTS users(
          username TEXT PRIMARY KEY, salt BLOB NOT NULL, pw_hash BLOB NOT NULL,
          is_admin INTEGER NOT NULL DEFAULT 0, created REAL NOT NULL);
        CREATE TABLE IF NOT EXISTS sessions(
          token_hash TEXT PRIMARY KEY, username TEXT NOT NULL, expires REAL NOT NULL);
        CREATE TABLE IF NOT EXISTS drops(
          id INTEGER PRIMARY KEY AUTOINCREMENT, sender TEXT NOT NULL, recipient TEXT NOT NULL,
          kind TEXT NOT NULL, filename TEXT NOT NULL, size INTEGER NOT NULL,
          created REAL NOT NULL, read_at REAL, data BLOB NOT NULL);
        CREATE TABLE IF NOT EXISTS messages(
          id INTEGER PRIMARY KEY AUTOINCREMENT, room TEXT NOT NULL, sender TEXT NOT NULL,
          ts REAL NOT NULL, ct TEXT NOT NULL);
        CREATE INDEX IF NOT EXISTS idx_msg_room ON messages(room, id);
        """)


def hash_pw(password: str, salt: bytes) -> bytes:
    return hashlib.scrypt(password.encode(), salt=salt, n=2 ** 14, r=8, p=1, maxmem=64 * 1024 * 1024, dklen=32)


def create_user(con, username: str, password: str, is_admin: bool = False):
    salt = secrets.token_bytes(16)
    con.execute("INSERT INTO users(username,salt,pw_hash,is_admin,created) VALUES(?,?,?,?,?)",
                (username, salt, hash_pw(password, salt), int(is_admin), time.time()))


def valid_password(pw: str) -> str:
    if not isinstance(pw, str) or len(pw) < 8 or len(pw) > 200:
        raise HTTPException(400, "Password must be 8-200 characters.")
    return pw


@app.on_event("startup")
def startup():
    init_db()
    admin = os.environ.get("ADMIN_USER", "admin").strip().lower()
    pw = os.environ.get("ADMIN_PASSWORD", "")
    with db() as con:
        if pw and not con.execute("SELECT 1 FROM users WHERE username=?", (admin,)).fetchone():
            create_user(con, admin, pw, True)
            print(f"[hub] created admin '{admin}'")
        elif not con.execute("SELECT 1 FROM users").fetchone():
            generated = secrets.token_urlsafe(12)
            create_user(con, admin, generated, True)
            print(f"[hub] No users and no ADMIN_PASSWORD set. Created '{admin}' with password: {generated}")
        con.execute("DELETE FROM sessions WHERE expires < ?", (time.time(),))


# --------------------------------------------------------------------------
# Auth helpers
# --------------------------------------------------------------------------

FAILS: dict = {}  # key -> [timestamps]


def throttled(key: str) -> bool:
    now = time.time()
    FAILS[key] = [t for t in FAILS.get(key, []) if now - t < 600]
    return len(FAILS[key]) >= 6


def user_from_token(token: str | None):
    if not token:
        return None
    h = hashlib.sha256(token.encode()).hexdigest()
    with db() as con:
        row = con.execute("SELECT u.username, u.is_admin FROM sessions s JOIN users u USING(username) "
                          "WHERE s.token_hash=? AND s.expires>?", (h, time.time())).fetchone()
    return {"username": row["username"], "is_admin": bool(row["is_admin"])} if row else None


def current_user(request: Request):
    user = user_from_token(request.cookies.get("sid"))
    if not user:
        raise HTTPException(401, "Not logged in.")
    if request.method not in ("GET", "HEAD") and request.headers.get("x-requested-with") != "stego":
        raise HTTPException(403, "Bad request.")
    return user


def admin_user(user=Depends(current_user)):
    if not user["is_admin"]:
        raise HTTPException(403, "Admins only.")
    return user


@app.middleware("http")
async def security_headers(request: Request, call_next):
    resp = await call_next(request)
    resp.headers["Content-Security-Policy"] = (
        "default-src 'self'; img-src 'self' blob: data:; media-src 'self' blob: data:; "
        "style-src 'self' 'unsafe-inline'; script-src 'self'; connect-src 'self' ws: wss:; "
        "frame-ancestors 'none'; base-uri 'none'; form-action 'self'")
    resp.headers["X-Content-Type-Options"] = "nosniff"
    resp.headers["Referrer-Policy"] = "no-referrer"
    resp.headers["X-Frame-Options"] = "DENY"
    if request.url.path.startswith("/api"):
        resp.headers["Cache-Control"] = "no-store"
    return resp


# --------------------------------------------------------------------------
# Auth endpoints
# --------------------------------------------------------------------------

@app.post("/api/login")
async def login(request: Request, response: Response):
    if request.headers.get("x-requested-with") != "stego":
        raise HTTPException(403, "Bad request.")
    body = await request.json()
    username = str(body.get("username", "")).strip().lower()
    password = str(body.get("password", ""))
    ip = request.client.host if request.client else "?"
    if throttled(f"u:{username}") or throttled(f"i:{ip}"):
        raise HTTPException(429, "Too many failed attempts. Try again in 10 minutes.")
    with db() as con:
        row = con.execute("SELECT * FROM users WHERE username=?", (username,)).fetchone()
    salt = row["salt"] if row else b"\0" * 16
    ok = hmac.compare_digest(hash_pw(password, salt), row["pw_hash"] if row else b"\0" * 32) and row is not None
    if not ok:
        now = time.time()
        FAILS.setdefault(f"u:{username}", []).append(now)
        FAILS.setdefault(f"i:{ip}", []).append(now)
        raise HTTPException(401, "Wrong username or password.")
    token = secrets.token_urlsafe(32)
    with db() as con:
        con.execute("INSERT INTO sessions VALUES(?,?,?)",
                    (hashlib.sha256(token.encode()).hexdigest(), username, time.time() + SESSION_TTL))
    response.set_cookie("sid", token, max_age=SESSION_TTL, httponly=True, samesite="strict",
                        secure=request.url.scheme == "https", path="/")
    return {"username": username, "is_admin": bool(row["is_admin"])}


@app.post("/api/logout")
def logout(request: Request, response: Response, user=Depends(current_user)):
    token = request.cookies.get("sid", "")
    with db() as con:
        con.execute("DELETE FROM sessions WHERE token_hash=?", (hashlib.sha256(token.encode()).hexdigest(),))
    response.delete_cookie("sid", path="/")
    return {"ok": True}


@app.get("/api/me")
def me(user=Depends(current_user)):
    return user


@app.post("/api/password")
async def change_password(request: Request, user=Depends(current_user)):
    body = await request.json()
    new = valid_password(body.get("new"))
    with db() as con:
        row = con.execute("SELECT * FROM users WHERE username=?", (user["username"],)).fetchone()
        if not hmac.compare_digest(hash_pw(str(body.get("old", "")), row["salt"]), row["pw_hash"]):
            raise HTTPException(401, "Current password is wrong.")
        salt = secrets.token_bytes(16)
        con.execute("UPDATE users SET salt=?, pw_hash=? WHERE username=?", (salt, hash_pw(new, salt), user["username"]))
    return {"ok": True}


@app.get("/api/users")
def users(user=Depends(current_user)):
    with db() as con:
        rows = con.execute("SELECT username, is_admin, created FROM users ORDER BY username").fetchall()
    return [{"username": r["username"], "is_admin": bool(r["is_admin"]), "created": r["created"]} for r in rows]


# --------------------------------------------------------------------------
# Admin
# --------------------------------------------------------------------------

@app.post("/api/admin/users")
async def admin_create(request: Request, admin=Depends(admin_user)):
    body = await request.json()
    username = str(body.get("username", "")).strip().lower()
    if not USER_RE.match(username):
        raise HTTPException(400, "Username: 2-24 chars, a-z 0-9 _ . -")
    pw = valid_password(body.get("password"))
    with db() as con:
        if con.execute("SELECT 1 FROM users WHERE username=?", (username,)).fetchone():
            raise HTTPException(409, "That username already exists.")
        create_user(con, username, pw, bool(body.get("is_admin")))
    return {"ok": True}


@app.post("/api/admin/users/{username}/password")
async def admin_reset(username: str, request: Request, admin=Depends(admin_user)):
    body = await request.json()
    pw = valid_password(body.get("password"))
    salt = secrets.token_bytes(16)
    with db() as con:
        cur = con.execute("UPDATE users SET salt=?, pw_hash=? WHERE username=?", (salt, hash_pw(pw, salt), username))
        if not cur.rowcount:
            raise HTTPException(404, "No such user.")
        con.execute("DELETE FROM sessions WHERE username=?", (username,))
    return {"ok": True}


@app.delete("/api/admin/users/{username}")
def admin_delete(username: str, admin=Depends(admin_user)):
    if username == admin["username"]:
        raise HTTPException(400, "You can't delete yourself.")
    with db() as con:
        con.execute("DELETE FROM users WHERE username=?", (username,))
        con.execute("DELETE FROM sessions WHERE username=?", (username,))
        con.execute("DELETE FROM drops WHERE sender=? OR recipient=?", (username, username))
    return {"ok": True}


# --------------------------------------------------------------------------
# Drops (opaque encrypted blobs addressed to one user)
# --------------------------------------------------------------------------

def purge_old():
    with db() as con:
        con.execute("DELETE FROM drops WHERE created < ?", (time.time() - DROP_TTL,))


@app.get("/api/drops")
def list_drops(user=Depends(current_user)):
    purge_old()
    name = user["username"]
    with db() as con:
        rows = con.execute("SELECT id,sender,recipient,kind,filename,size,created,read_at FROM drops "
                           "WHERE sender=? OR recipient=? ORDER BY id DESC", (name, name)).fetchall()
    return [dict(r) for r in rows]


@app.post("/api/drops")
async def create_drop(request: Request, user=Depends(current_user)):
    to = request.headers.get("x-to", "").strip().lower()
    kind = request.headers.get("x-kind", "")
    filename = unquote(request.headers.get("x-filename", "file"))[:120] or "file"
    if kind not in KINDS:
        raise HTTPException(400, "Bad kind.")
    declared = int(request.headers.get("content-length") or 0)
    if declared > MAX_UPLOAD:
        raise HTTPException(413, f"Too large (max {MAX_UPLOAD // 1048576} MB).")
    chunks, total = [], 0
    async for chunk in request.stream():
        total += len(chunk)
        if total > MAX_UPLOAD:
            raise HTTPException(413, f"Too large (max {MAX_UPLOAD // 1048576} MB).")
        chunks.append(chunk)
    data = b"".join(chunks)
    if not data:
        raise HTTPException(400, "Empty upload.")
    with db() as con:
        if not con.execute("SELECT 1 FROM users WHERE username=?", (to,)).fetchone():
            raise HTTPException(404, "No such recipient.")
        count = con.execute("SELECT COUNT(*) FROM drops WHERE recipient=?", (to,)).fetchone()[0]
        if count >= MAX_DROPS_PER_USER:
            raise HTTPException(409, "That user's inbox is full.")
        cur = con.execute("INSERT INTO drops(sender,recipient,kind,filename,size,created,data) VALUES(?,?,?,?,?,?,?)",
                          (user["username"], to, kind, filename, len(data), time.time(), data))
    return {"id": cur.lastrowid}


@app.get("/api/drops/{drop_id}/file")
def drop_file(drop_id: int, user=Depends(current_user)):
    with db() as con:
        row = con.execute("SELECT * FROM drops WHERE id=?", (drop_id,)).fetchone()
        if not row or user["username"] not in (row["sender"], row["recipient"]):
            raise HTTPException(404, "Not found.")
        if row["recipient"] == user["username"] and row["read_at"] is None:
            con.execute("UPDATE drops SET read_at=? WHERE id=?", (time.time(), drop_id))
    return Response(row["data"], media_type="application/octet-stream")


@app.delete("/api/drops/{drop_id}")
def delete_drop(drop_id: int, user=Depends(current_user)):
    with db() as con:
        con.execute("DELETE FROM drops WHERE id=? AND (sender=? OR recipient=?)",
                    (drop_id, user["username"], user["username"]))
    return {"ok": True}


# --------------------------------------------------------------------------
# Live chat (server relays ciphertext only)
# --------------------------------------------------------------------------

ROOMS: dict[str, dict] = {}  # room -> {WebSocket: username}


@app.get("/api/rooms")
def rooms(user=Depends(current_user)):
    with db() as con:
        names = {r[0] for r in con.execute("SELECT DISTINCT room FROM messages")}
    names |= set(ROOMS)
    names.add("general")
    return sorted(names)


async def broadcast(room: str, payload: dict):
    text = json.dumps(payload)
    for ws in list(ROOMS.get(room, {})):
        try:
            await ws.send_text(text)
        except Exception:
            ROOMS.get(room, {}).pop(ws, None)


def presence(room: str):
    return sorted(set(ROOMS.get(room, {}).values()))


@app.websocket("/ws")
async def chat_ws(ws: WebSocket):
    origin = ws.headers.get("origin")
    if origin and urlparse(origin).netloc != ws.headers.get("host"):
        await ws.close(code=1008)
        return
    user = user_from_token(ws.cookies.get("sid"))
    room = ws.query_params.get("room", "general")
    if not user or not ROOM_RE.match(room):
        await ws.close(code=1008)
        return
    await ws.accept()
    ROOMS.setdefault(room, {})[ws] = user["username"]
    with db() as con:
        rows = con.execute("SELECT id,sender,ts,ct FROM messages WHERE room=? ORDER BY id DESC LIMIT ?",
                           (room, HISTORY)).fetchall()
    await ws.send_text(json.dumps({"type": "history", "messages": [
        {"id": r["id"], "user": r["sender"], "ts": r["ts"], "ct": r["ct"]} for r in reversed(rows)]}))
    await broadcast(room, {"type": "presence", "users": presence(room)})
    last = []
    try:
        while True:
            data = json.loads(await ws.receive_text())
            if data.get("type") != "msg":
                continue
            ct = data.get("ct")
            now = time.time()
            last = [t for t in last if now - t < 10]
            if not isinstance(ct, str) or not ct or len(ct) > MAX_CHAT_CT or len(last) >= 20:
                continue
            last.append(now)
            with db() as con:
                cur = con.execute("INSERT INTO messages(room,sender,ts,ct) VALUES(?,?,?,?)",
                                  (room, user["username"], now, ct))
                con.execute("DELETE FROM messages WHERE room=? AND id <= "
                            "(SELECT id FROM messages WHERE room=? ORDER BY id DESC LIMIT 1 OFFSET 500)", (room, room))
            await broadcast(room, {"type": "msg", "id": cur.lastrowid, "user": user["username"], "ts": now, "ct": ct})
    except (WebSocketDisconnect, json.JSONDecodeError, RuntimeError):
        pass
    finally:
        ROOMS.get(room, {}).pop(ws, None)
        if room in ROOMS and not ROOMS[room]:
            ROOMS.pop(room)
        else:
            await broadcast(room, {"type": "presence", "users": presence(room)})


# --------------------------------------------------------------------------
# Static frontend
# --------------------------------------------------------------------------

@app.get("/")
def index():
    return FileResponse(BASE / "static" / "index.html", headers={"Cache-Control": "no-cache"})


app.mount("/static", StaticFiles(directory=BASE / "static"), name="static")
