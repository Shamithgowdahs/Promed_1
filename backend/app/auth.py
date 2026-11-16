import base64
import hashlib
import hmac
import os
import secrets
from datetime import datetime, timedelta, timezone

from fastapi import Depends, HTTPException, Request, Response
from sqlalchemy import select
from sqlalchemy.orm import Session, joinedload

from backend.app.db import get_db
from backend.app.models import AccountUser, UserSession

CUSTOMER_SESSION_COOKIE = "promed_customer_session"
STAFF_SESSION_COOKIE = "promed_staff_session"
SESSION_LIFETIME = timedelta(days=30)
PASSWORD_ITERATIONS = 600_000


def hash_password(password: str) -> str:
    salt = secrets.token_bytes(16)
    derived = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt, PASSWORD_ITERATIONS)
    return "pbkdf2_sha256${}${}${}".format(
        PASSWORD_ITERATIONS,
        base64.urlsafe_b64encode(salt).decode("ascii"),
        base64.urlsafe_b64encode(derived).decode("ascii"),
    )


def verify_password(password: str, stored_hash: str | None) -> bool:
    if not stored_hash:
        hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), b"\0" * 16, PASSWORD_ITERATIONS)
        return False
    try:
        algorithm, iterations_text, salt_text, expected_text = stored_hash.split("$", 3)
        if algorithm != "pbkdf2_sha256":
            return False
        iterations = int(iterations_text)
        if iterations < 100_000 or iterations > 2_000_000:
            return False
        salt = base64.urlsafe_b64decode(salt_text.encode("ascii"))
        expected = base64.urlsafe_b64decode(expected_text.encode("ascii"))
    except (ValueError, TypeError):
        return False
    actual = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt, iterations)
    return hmac.compare_digest(actual, expected)


def issue_session(db: Session, user: AccountUser) -> str:
    raw_token = secrets.token_urlsafe(32)
    session_type = "customer" if user.role == "customer" else "staff"
    db.add(
        UserSession(
            user_id=user.id,
            token_hash=hashlib.sha256(raw_token.encode("ascii")).hexdigest(),
            session_type=session_type,
            expires_at=datetime.now(timezone.utc) + SESSION_LIFETIME,
        )
    )
    return raw_token


def set_session_cookie(response: Response, token: str, session_type: str) -> None:
    response.set_cookie(
        key=CUSTOMER_SESSION_COOKIE if session_type == "customer" else STAFF_SESSION_COOKIE,
        value=token,
        max_age=int(SESSION_LIFETIME.total_seconds()),
        httponly=True,
        secure=os.getenv("PROMED_COOKIE_SECURE", "").lower() in {"1", "true", "yes"},
        samesite="lax",
        path="/api",
    )


def clear_session_cookie(response: Response, session_type: str) -> None:
    response.delete_cookie(
        key=CUSTOMER_SESSION_COOKIE if session_type == "customer" else STAFF_SESSION_COOKIE,
        httponly=True,
        secure=os.getenv("PROMED_COOKIE_SECURE", "").lower() in {"1", "true", "yes"},
        samesite="lax",
        path="/api",
    )


def _session_user(request: Request, db: Session, session_type: str) -> AccountUser:
    cookie_name = CUSTOMER_SESSION_COOKIE if session_type == "customer" else STAFF_SESSION_COOKIE
    raw_token = request.cookies.get(cookie_name)
    if not raw_token:
        raise HTTPException(status_code=401, detail="Sign in is required")
    token_hash = hashlib.sha256(raw_token.encode("ascii", errors="ignore")).hexdigest()
    session = db.scalar(
        select(UserSession)
        .options(joinedload(UserSession.user))
        .where(
            UserSession.token_hash == token_hash,
            UserSession.session_type == session_type,
            UserSession.revoked_at.is_(None),
        )
    )
    if session is None or not session.user.active:
        raise HTTPException(status_code=401, detail="Session is invalid or expired")
    expires_at = session.expires_at
    if expires_at.tzinfo is None:
        expires_at = expires_at.replace(tzinfo=timezone.utc)
    if expires_at <= datetime.now(timezone.utc):
        raise HTTPException(status_code=401, detail="Session is invalid or expired")
    return session.user


def require_customer(request: Request, db: Session = Depends(get_db)) -> AccountUser:
    user = _session_user(request, db, "customer")
    if user.role != "customer":
        raise HTTPException(status_code=403, detail="Customer access is required")
    return user


def require_staff(request: Request, db: Session = Depends(get_db)) -> AccountUser:
    user = _session_user(request, db, "staff")
    if user.role not in {"owner", "pharmacist", "operator"}:
        raise HTTPException(status_code=403, detail="Staff access is required")
    return user


def require_owner(user: AccountUser = Depends(require_staff)) -> AccountUser:
    if user.role != "owner":
        raise HTTPException(status_code=403, detail="Owner access is required")
    return user
