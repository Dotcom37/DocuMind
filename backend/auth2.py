import base64
import hashlib
import hmac
import json
import os
import secrets
import smtplib
import urllib.parse
import urllib.request
from datetime import datetime, timedelta, timezone
from email.message import EmailMessage
from functools import wraps

from flask import Blueprint, jsonify, redirect, request, session, url_for, make_response
from werkzeug.security import check_password_hash, generate_password_hash

from .config.extensions import db
from .models import OTP, User


auth_bp = Blueprint("auth", __name__, url_prefix="/auth")


def _frontend_url(path=""):
    return os.getenv("FRONTEND_URL", "http://localhost:5173").rstrip("/") + path


def _secret():
    return os.getenv("JWT_SECRET_KEY", "change-this-in-production").encode()


def _b64(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).rstrip(b"=").decode()


def _make_token(user_id: int, expires_hours=24):
    header = _b64(json.dumps({"alg": "HS256", "typ": "JWT"}, separators=(",", ":")).encode())
    payload = _b64(json.dumps({"sub": str(user_id), "exp": int((datetime.now(timezone.utc) + timedelta(hours=expires_hours)).timestamp())}, separators=(",", ":")).encode())
    signing = f"{header}.{payload}".encode()
    signature = _b64(hmac.new(_secret(), signing, hashlib.sha256).digest())
    return f"{header}.{payload}.{signature}"


def _read_token(token):
    try:
        header, payload, signature = token.split(".")
        expected = _b64(hmac.new(_secret(), f"{header}.{payload}".encode(), hashlib.sha256).digest())
        if not hmac.compare_digest(signature, expected):
            return None
        data = json.loads(base64.urlsafe_b64decode(payload + "=" * (-len(payload) % 4)))
        if int(data["exp"]) < int(datetime.now(timezone.utc).timestamp()):
            return None
        return int(data["sub"])
    except Exception:
        return None


def _set_auth_cookie(response, user_id):
    response.set_cookie(
        "access_token", _make_token(user_id), httponly=True,
        secure=os.getenv("COOKIE_SECURE", "false").lower() == "true",
        samesite=os.getenv("COOKIE_SAMESITE", "Lax"), max_age=86400, path="/",
    )
    response.set_cookie("csrf_token", secrets.token_urlsafe(32), httponly=False,
                        secure=os.getenv("COOKIE_SECURE", "false").lower() == "true",
                        samesite=os.getenv("COOKIE_SAMESITE", "Lax"), max_age=86400, path="/")


def current_user():
    token = request.cookies.get("access_token")
    user_id = _read_token(token) if token else None
    return db.session.get(User, user_id) if user_id else None


def require_verified_user(fn):
    @wraps(fn)
    def wrapper(*args, **kwargs):
        if request.method not in ("GET", "HEAD", "OPTIONS"):
            csrf_cookie = request.cookies.get("csrf_token")
            csrf_header = request.headers.get("X-CSRF-TOKEN")
            if not csrf_cookie or not csrf_header or not hmac.compare_digest(csrf_cookie, csrf_header):
                return {"error": "CSRF validation failed"}, 403
        user = current_user()
        if not user:
            return {"error": "Authentication required"}, 401
        if not user.is_verified:
            return {"error": "Email verification required"}, 403
        return fn(user, *args, **kwargs)
    return wrapper


def _send_otp_email(email: str, otp: str):
    host = os.getenv("SMTP_HOST")
    port = int(os.getenv("SMTP_PORT", "587"))
    username = os.getenv("SMTP_USERNAME")
    password = os.getenv("SMTP_PASSWORD")
    sender = os.getenv("SMTP_FROM", username or "")
    if not all([host, username, password, sender]):
        print(f"[DEV OTP] {email}: {otp}")
        return
    msg = EmailMessage()
    msg["Subject"] = "Your RAG Chat verification code"
    msg["From"] = sender
    msg["To"] = email
    msg.set_content(f"Your RAG Chat verification code is {otp}.\n\nIt expires in 10 minutes.")
    with smtplib.SMTP(host, port, timeout=15) as server:
        server.starttls(); server.login(username, password); server.send_message(msg)


def _issue_otp(user):
    OTP.query.filter_by(user_id=user.id, used=False).update({"used": True})
    code = f"{secrets.randbelow(1_000_000):06d}"
    db.session.add(OTP(user_id=user.id, otp_hash=generate_password_hash(code),
                       expires_at=datetime.now(timezone.utc) + timedelta(minutes=10), attempts=0, used=False))
    db.session.commit()
    _send_otp_email(user.email, code)


def _auth_response(user):
    response = jsonify({"message": "Authentication successful", "user": user.to_dict()})
    _set_auth_cookie(response, user.id)
    return response


@auth_bp.post("/register")
def register():
    data = request.get_json(silent=True) or {}
    name, email, password = (data.get("name") or "").strip(), (data.get("email") or "").strip().lower(), data.get("password") or ""
    if not name or not email or not password: return {"error": "name, email and password are required"}, 400
    if len(password) < 8: return {"error": "Password must be at least 8 characters"}, 400
    user = User.query.filter_by(email=email).first()
    if user and user.is_verified: return {"error": "An account with this email already exists"}, 409
    if user:
        user.name = name; user.password_hash = generate_password_hash(password)
    else:
        user = User(name=name, email=email, password_hash=generate_password_hash(password), is_verified=False)
        db.session.add(user); db.session.flush()
    db.session.commit(); _issue_otp(user)
    return {"message": "OTP sent", "email": email}, 201


@auth_bp.post("/verify-otp")
def verify_otp():
    data = request.get_json(silent=True) or {}; email = (data.get("email") or "").strip().lower(); code = str(data.get("otp") or "").strip()
    user = User.query.filter_by(email=email).first()
    if not user: return {"error": "Invalid verification request"}, 400
    record = OTP.query.filter_by(user_id=user.id, used=False).order_by(OTP.created_at.desc()).first()
    if not record: return {"error": "OTP not found. Request a new OTP."}, 400
    expires = record.expires_at.replace(tzinfo=timezone.utc) if record.expires_at.tzinfo is None else record.expires_at
    if datetime.now(timezone.utc) > expires:
        record.used = True; db.session.commit(); return {"error": "OTP expired. Request a new OTP."}, 400
    if record.attempts >= 5:
        record.used = True; db.session.commit(); return {"error": "Too many OTP attempts. Request a new OTP."}, 429
    record.attempts += 1
    if not check_password_hash(record.otp_hash, code): db.session.commit(); return {"error": "Invalid OTP"}, 400
    record.used = True; user.is_verified = True; db.session.commit(); return _auth_response(user)


@auth_bp.post("/resend-otp")
def resend_otp():
    data = request.get_json(silent=True) or {}; email = (data.get("email") or "").strip().lower(); user = User.query.filter_by(email=email).first()
    if not user: return {"message": "If the account exists, a new OTP has been sent"}, 200
    if user.is_verified: return {"error": "Email is already verified"}, 400
    _issue_otp(user); return {"message": "OTP sent"}, 200


@auth_bp.post("/login")
def login():
    data = request.get_json(silent=True) or {}; email = (data.get("email") or "").strip().lower(); password = data.get("password") or ""
    user = User.query.filter_by(email=email).first()
    if not user or not user.password_hash or not check_password_hash(user.password_hash, password): return {"error": "Invalid email or password"}, 401
    if not user.is_verified:
        _issue_otp(user); return {"error": "Email not verified", "requires_verification": True, "email": user.email}, 403
    return _auth_response(user)


@auth_bp.get("/me")
def me():
    user = current_user()
    if not user: return {"error": "Authentication required"}, 401
    return {"user": user.to_dict()}, 200


@auth_bp.post("/logout")
def logout():
    response = jsonify({"message": "Logged out"}); response.delete_cookie("access_token", path="/"); response.delete_cookie("csrf_token", path="/"); return response


@auth_bp.get("/google")
def google_login():
    client_id = os.getenv("GOOGLE_CLIENT_ID")
    if not client_id or not os.getenv("GOOGLE_CLIENT_SECRET"): return {"error": "Google login is not configured"}, 503
    print("GOOGLE REDIRECT URI:", url_for("auth.google_callback",
    _external=True
    ))
    state = secrets.token_urlsafe(32); session["google_oauth_state"] = state
    params = {"client_id": client_id, "redirect_uri": url_for("auth.google_callback", _external=True), "response_type": "code", "scope": "openid email profile", "state": state, "access_type": "offline", "prompt": "select_account"}
    return redirect("https://accounts.google.com/o/oauth2/v2/auth?" + urllib.parse.urlencode(params))


@auth_bp.get("/google/callback")
def google_callback():
    if request.args.get("state") != session.pop("google_oauth_state", None): return redirect(_frontend_url("/login?error=invalid_oauth_state"))
    code = request.args.get("code")
    if not code: return redirect(_frontend_url("/login?error=google_auth_failed"))
    client_id, client_secret = os.getenv("GOOGLE_CLIENT_ID"), os.getenv("GOOGLE_CLIENT_SECRET")
    token_data = urllib.parse.urlencode({"code": code, "client_id": client_id, "client_secret": client_secret, "redirect_uri": url_for("auth.google_callback", _external=True), "grant_type": "authorization_code"}).encode()
    try:
        req = urllib.request.Request("https://oauth2.googleapis.com/token", data=token_data, headers={"Content-Type": "application/x-www-form-urlencoded"})
        token = json.loads(urllib.request.urlopen(req, timeout=15).read())
        access_token = token["access_token"]
        req = urllib.request.Request("https://openidconnect.googleapis.com/v1/userinfo", headers={"Authorization": f"Bearer {access_token}"})
        info = json.loads(urllib.request.urlopen(req, timeout=15).read())
    except Exception:
        return redirect(_frontend_url("/login?error=google_auth_failed"))
    email, google_id = (info.get("email") or "").strip().lower(), info.get("sub")
    if not email or not google_id: return redirect(_frontend_url("/login?error=google_missing_identity"))
    user = User.query.filter((User.google_id == google_id) | (User.email == email)).first()
    if not user:
        user = User(name=info.get("name") or email.split("@")[0], email=email, google_id=google_id, is_verified=True); db.session.add(user)
    else:
        user.google_id = user.google_id or google_id; user.name = user.name or info.get("name") or email.split("@")[0]; user.is_verified = True
    db.session.commit()
    response = redirect(_frontend_url("/")); _set_auth_cookie(response, user.id); return response
