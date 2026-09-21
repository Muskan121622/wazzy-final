import os
import hmac
import json
import uuid
import base64
import hashlib
import time
import re

from fastapi import Depends, HTTPException
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials

# Self-contained HS256 JWT (stdlib only — no PyJWT needed on Python 3.14)
SECRET_KEY = os.getenv("SECRET_KEY", "winter-is-coming-change-me-dev-secret")
TOKEN_TTL_SECONDS = 30 * 24 * 3600  # 30 days

from database.db import get_connection

_bearer = HTTPBearer(auto_error=False)

EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")


# ── Password hashing (PBKDF2, stdlib) ────────────────────────
def hash_password(password: str) -> str:
    salt = os.urandom(16)
    digest = hashlib.pbkdf2_hmac("sha256", password.encode(), salt, 200_000)
    return f"pbkdf2${salt.hex()}${digest.hex()}"


def verify_password(password: str, stored: str) -> bool:
    try:
        _, salt_hex, digest_hex = stored.split("$")
        digest = hashlib.pbkdf2_hmac("sha256", password.encode(), bytes.fromhex(salt_hex), 200_000)
        return hmac.compare_digest(digest.hex(), digest_hex)
    except Exception:
        return False


# ── Tokens ───────────────────────────────────────────────────
def _b64url(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).decode().rstrip("=")


def _b64url_decode(s: str) -> bytes:
    return base64.urlsafe_b64decode(s + "=" * (-len(s) % 4))


def create_token(user_id: str) -> str:
    header = _b64url(json.dumps({"alg": "HS256", "typ": "JWT"}).encode())
    payload = _b64url(json.dumps({
        "sub": user_id,
        "iat": int(time.time()),
        "exp": int(time.time()) + TOKEN_TTL_SECONDS,
    }).encode())
    sig = _b64url(hmac.new(SECRET_KEY.encode(), f"{header}.{payload}".encode(), hashlib.sha256).digest())
    return f"{header}.{payload}.{sig}"


def decode_token(token: str) -> str | None:
    try:
        header, payload, sig = token.split(".")
        expected = _b64url(hmac.new(SECRET_KEY.encode(), f"{header}.{payload}".encode(), hashlib.sha256).digest())
        if not hmac.compare_digest(sig, expected):
            return None
        data = json.loads(_b64url_decode(payload))
        if data.get("exp", 0) < time.time():
            return None
        return data.get("sub")
    except Exception:
        return None


# ── User records ─────────────────────────────────────────────
def create_user(name: str, email: str | None, password: str | None, is_guest: bool = False) -> dict:
    user_id = "guest_" + uuid.uuid4().hex[:10] if is_guest else "user_" + uuid.uuid4().hex[:10]
    conn = get_connection()
    cur = conn.cursor()
    cur.execute(
        "INSERT INTO users (id, name, email, password_hash, is_guest) VALUES (?, ?, ?, ?, ?)",
        (user_id, name, email, hash_password(password) if password else None, is_guest),
    )
    conn.commit()
    conn.close()
    return {"id": user_id, "name": name, "email": email, "is_guest": is_guest}


def find_user_by_email(email: str) -> dict | None:
    conn = get_connection()
    cur = conn.cursor()
    cur.execute("SELECT * FROM users WHERE lower(email) = lower(?)", (email,))
    row = cur.fetchone()
    conn.close()
    return row


def get_user(user_id: str) -> dict | None:
    conn = get_connection()
    cur = conn.cursor()
    cur.execute("SELECT * FROM users WHERE id = ?", (user_id,))
    row = cur.fetchone()
    conn.close()
    return row


def register_user(name: str, email: str, password: str) -> dict:
    name = (name or "").strip()
    email = (email or "").strip()
    if not name or len(name) < 2:
        raise HTTPException(status_code=422, detail="Name must be at least 2 characters")
    if not EMAIL_RE.match(email):
        raise HTTPException(status_code=422, detail="Invalid email address")
    if not password or len(password) < 6:
        raise HTTPException(status_code=422, detail="Password must be at least 6 characters")
    if find_user_by_email(email):
        raise HTTPException(status_code=409, detail="An account with this email already exists")
    return create_user(name, email, password)


def login_user(email: str, password: str) -> dict:
    user = find_user_by_email(email)
    if not user or not user.get("password_hash") or not verify_password(password, user["password_hash"]):
        raise HTTPException(status_code=401, detail="Invalid email or password")
    return user


# ── FastAPI dependency ───────────────────────────────────────
def get_current_user(creds: HTTPAuthorizationCredentials | None = Depends(_bearer)) -> dict:
    if creds is None or not creds.credentials:
        raise HTTPException(status_code=401, detail="Missing Authorization: Bearer <token>")
    user_id = decode_token(creds.credentials)
    if not user_id:
        raise HTTPException(status_code=401, detail="Invalid or expired token")
    user = get_user(user_id)
    if not user:
        raise HTTPException(status_code=401, detail="User no longer exists")
    return user


# ── Trip ownership guard ─────────────────────────────────────
def assert_trip_ownership(trip_id: str, user_id: str) -> dict:
    conn = get_connection()
    cur = conn.cursor()
    cur.execute("SELECT * FROM trips WHERE id = ?", (trip_id,))
    trip = cur.fetchone()
    conn.close()
    if not trip:
        raise HTTPException(status_code=404, detail="Trip not found")
    if trip["user_id"] != user_id:
        raise HTTPException(status_code=403, detail="This trip belongs to another user")
    return trip
