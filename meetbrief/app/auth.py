"""Password hashing, opaque sessions, and backend role checks."""
import hashlib
import hmac
import secrets
from datetime import datetime, timedelta, timezone
from fastapi import Depends, HTTPException, Request
from app.config import settings
from app.db import connect, db_session, utc_now

COOKIE_NAME = "meetbrief_session"
ITERATIONS = 310_000


def hash_password(password: str) -> str:
    salt = secrets.token_bytes(16)
    derived = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt, ITERATIONS)
    return f"pbkdf2_sha256${ITERATIONS}${salt.hex()}${derived.hex()}"


def verify_password(password: str, stored: str) -> bool:
    try:
        algorithm, count, salt_hex, digest_hex = stored.split("$", 3)
        if algorithm != "pbkdf2_sha256":
            return False
        expected = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), bytes.fromhex(salt_hex), int(count)).hex()
        return hmac.compare_digest(expected, digest_hex)
    except (ValueError, TypeError):
        return False


def _token_hash(token: str) -> str:
    return hmac.new(settings.app_secret.encode("utf-8"), token.encode("utf-8"), hashlib.sha256).hexdigest()


def make_session(user_id: int) -> tuple[str, str]:
    raw = secrets.token_urlsafe(36)
    csrf = secrets.token_urlsafe(24)
    expires = (datetime.now(timezone.utc) + timedelta(hours=settings.session_hours)).isoformat(timespec="seconds")
    with db_session() as db:
        db.execute("INSERT INTO sessions(token_hash,user_id,csrf_token,expires_at,created_at) VALUES(?,?,?,?,?)",
                   (_token_hash(raw), user_id, csrf, expires, utc_now()))
    return raw, csrf


def current_user(request: Request, write: bool = False) -> dict:
    token = request.cookies.get(COOKIE_NAME)
    if not token:
        raise HTTPException(status_code=401, detail="Please sign in to continue.")
    with db_session() as db:
        row = db.execute("""SELECT u.id,u.username,u.role,u.active,s.csrf_token,s.expires_at,s.token_hash
            FROM sessions s JOIN users u ON u.id=s.user_id WHERE s.token_hash=?""", (_token_hash(token),)).fetchone()
        if not row:
            raise HTTPException(status_code=401, detail="Session expired. Please sign in again.")
        expires = datetime.fromisoformat(row["expires_at"])
        if expires <= datetime.now(timezone.utc) or not row["active"]:
            db.execute("DELETE FROM sessions WHERE token_hash=?", (_token_hash(token),))
            raise HTTPException(status_code=401, detail="Session expired. Please sign in again.")
        if write:
            supplied = request.headers.get("x-csrf-token", "")
            if not supplied or not hmac.compare_digest(supplied, row["csrf_token"]):
                raise HTTPException(status_code=403, detail="Security token missing or invalid. Refresh and try again.")
        return {"id": row["id"], "username": row["username"], "role": row["role"], "csrf_token": row["csrf_token"]}


def require_user(request: Request) -> dict:
    return current_user(request)


def require_editor(request: Request) -> dict:
    user = current_user(request, write=True)
    if user["role"] not in {"Admin", "Editor/Reviewer"}:
        raise HTTPException(status_code=403, detail="Editor/Reviewer access is required for this change.")
    return user


def require_admin(request: Request) -> dict:
    user = current_user(request, write=True)
    if user["role"] != "Admin":
        raise HTTPException(status_code=403, detail="Admin access is required for this action.")
    return user


def authenticate(username: str, password: str) -> dict | None:
    with db_session() as db:
        row = db.execute("SELECT id,username,password_hash,role FROM users WHERE username=? COLLATE NOCASE AND active=1", (username,)).fetchone()
    if not row or not verify_password(password, row["password_hash"]):
        return None
    return {"id": row["id"], "username": row["username"], "role": row["role"]}
