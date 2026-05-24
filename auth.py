"""
auth.py — MongoDB-backed authentication for Fake Job Detector
Handles: signup, login, logout, session verification, route protection middleware
Uses:    pymongo, bcrypt, python-jose (JWT), httpOnly cookies
"""

import os
from datetime import datetime, timedelta

import bcrypt
from fastapi import APIRouter, Body, Request
from fastapi.responses import JSONResponse, RedirectResponse
from jose import JWTError, jwt
from pymongo import MongoClient
from pymongo.errors import ConnectionFailure
from starlette.middleware.base import BaseHTTPMiddleware

# ── CONFIG ────────────────────────────────────────────────────────────────────
MONGO_URI    = os.getenv("MONGO_URI", "mongodb://localhost:27017")
DB_NAME      = "fakejobdetector"
COLLECTION   = "users"

JWT_SECRET   = os.getenv("JWT_SECRET", "fjd_super_secret_key_change_in_prod")
JWT_ALGO     = "HS256"
JWT_EXPIRE_H = 24
COOKIE_NAME  = "fjd_session"

# Routes that do NOT require login
PUBLIC_PATHS = {"/", "/login", "/signup", "/favicon.ico"}
PUBLIC_PREFIXES = ("/static/", "/auth/")

# ── MONGO CONNECTION ──────────────────────────────────────────────────────────
try:
    _client = MongoClient(MONGO_URI, serverSelectionTimeoutMS=3000)
    _client.admin.command("ping")
    _db       = _client[DB_NAME]
    users_col = _db[COLLECTION]
    users_col.create_index("email", unique=True)
    print(f"✅ MongoDB connected — database: '{DB_NAME}'")
except ConnectionFailure:
    print("⚠️  MongoDB not reachable. Auth features will be disabled.")
    users_col = None

# ── ROUTER ────────────────────────────────────────────────────────────────────
router = APIRouter(prefix="/auth", tags=["auth"])

# ── HELPERS ───────────────────────────────────────────────────────────────────
def _hash_password(plain: str) -> str:
    return bcrypt.hashpw(plain.encode(), bcrypt.gensalt()).decode()

def _verify_password(plain: str, hashed: str) -> bool:
    return bcrypt.checkpw(plain.encode(), hashed.encode())

def _create_token(email: str, name: str) -> str:
    payload = {
        "sub":  email,
        "name": name,
        "exp":  datetime.utcnow() + timedelta(hours=JWT_EXPIRE_H),
    }
    return jwt.encode(payload, JWT_SECRET, algorithm=JWT_ALGO)

def _decode_token(token: str) -> dict | None:
    try:
        return jwt.decode(token, JWT_SECRET, algorithms=[JWT_ALGO])
    except JWTError:
        return None

def get_current_user(request: Request) -> dict | None:
    """Returns decoded JWT payload if the session cookie is valid, else None."""
    token = request.cookies.get(COOKIE_NAME)
    if not token:
        return None
    return _decode_token(token)

# ── MIDDLEWARE ────────────────────────────────────────────────────────────────
class AuthMiddleware(BaseHTTPMiddleware):
    """
    Intercepts every incoming request.
    - Public paths and /static/, /auth/ prefixes pass through freely.
    - Everything else requires a valid session cookie.
    - API routes (/predict) return 401 JSON instead of a redirect.
    """
    async def dispatch(self, request: Request, call_next):
        path = request.url.path

        # Always allow public paths and prefixes
        if path in PUBLIC_PATHS or any(path.startswith(p) for p in PUBLIC_PREFIXES):
            return await call_next(request)

        # Check session cookie
        user = get_current_user(request)
        if user is None:
            # API calls get a JSON 401, page requests get redirected
            if path.startswith("/predict") or request.headers.get("content-type", "").startswith("application/json"):
                return JSONResponse(
                    {"ok": False, "error": "Not authenticated. Please log in."},
                    status_code=401
                )
            # Redirect to login, preserving the intended destination
            return RedirectResponse(url=f"/login?next={path}", status_code=302)

        # User is authenticated — attach user info to request state for downstream use
        request.state.user = user
        return await call_next(request)

# ── AUTH ROUTES ───────────────────────────────────────────────────────────────

@router.post("/signup")
async def signup(data: dict = Body(...)):
    if users_col is None:
        return JSONResponse({"ok": False, "error": "Database unavailable"}, status_code=503)

    name     = (data.get("name") or "").strip()
    email    = (data.get("email") or "").strip().lower()
    password = (data.get("password") or "").strip()

    if not name or not email or not password:
        return JSONResponse({"ok": False, "error": "All fields are required"}, status_code=400)
    if len(password) < 8:
        return JSONResponse({"ok": False, "error": "Password must be at least 8 characters"}, status_code=400)
    if "@" not in email:
        return JSONResponse({"ok": False, "error": "Invalid email address"}, status_code=400)
    if users_col.find_one({"email": email}):
        return JSONResponse({"ok": False, "error": "An account with this email already exists"}, status_code=409)

    users_col.insert_one({
        "name":       name,
        "email":      email,
        "password":   _hash_password(password),
        "created_at": datetime.utcnow(),
    })

    token    = _create_token(email, name)
    response = JSONResponse({"ok": True, "name": name, "email": email})
    response.set_cookie(
        key=COOKIE_NAME, value=token,
        httponly=True, samesite="lax",
        max_age=JWT_EXPIRE_H * 3600
    )
    return response


@router.post("/login")
async def login(data: dict = Body(...)):
    if users_col is None:
        return JSONResponse({"ok": False, "error": "Database unavailable"}, status_code=503)

    email    = (data.get("email") or "").strip().lower()
    password = (data.get("password") or "").strip()

    if not email or not password:
        return JSONResponse({"ok": False, "error": "Email and password are required"}, status_code=400)

    user = users_col.find_one({"email": email})
    if not user or not _verify_password(password, user["password"]):
        return JSONResponse({"ok": False, "error": "Invalid email or password"}, status_code=401)

    token    = _create_token(email, user["name"])
    response = JSONResponse({"ok": True, "name": user["name"], "email": email})
    response.set_cookie(
        key=COOKIE_NAME, value=token,
        httponly=True, samesite="lax",
        max_age=JWT_EXPIRE_H * 3600
    )
    return response


@router.post("/logout")
async def logout():
    response = RedirectResponse(url="/login", status_code=302)
    response.delete_cookie(COOKIE_NAME)
    return response


@router.get("/me")
async def me(request: Request):
    user = get_current_user(request)
    if not user:
        return JSONResponse({"ok": False, "error": "Not authenticated"}, status_code=401)
    return JSONResponse({"ok": True, "name": user["name"], "email": user["sub"]})


# ── CONFIG ────────────────────────────────────────────────────────────────────
MONGO_URI    = os.getenv("MONGO_URI", "mongodb://localhost:27017")
DB_NAME      = "fakejobdetector"
COLLECTION   = "users"

JWT_SECRET   = os.getenv("JWT_SECRET", "fjd_super_secret_key_change_in_prod")
JWT_ALGO     = "HS256"
JWT_EXPIRE_H = 24   # token valid for 24 hours
COOKIE_NAME  = "fjd_session"

# ── MONGO CONNECTION ──────────────────────────────────────────────────────────
try:
    _client = MongoClient(MONGO_URI, serverSelectionTimeoutMS=3000)
    _client.admin.command("ping")          # test connection immediately
    _db      = _client[DB_NAME]
    users_col = _db[COLLECTION]
    users_col.create_index("email", unique=True)   # enforce unique emails
    print(f"✅ MongoDB connected — database: '{DB_NAME}'")
except ConnectionFailure:
    print("⚠️  MongoDB not reachable. Auth features will be disabled.")
    users_col = None

# ── ROUTER ────────────────────────────────────────────────────────────────────
router = APIRouter(prefix="/auth", tags=["auth"])

# ── HELPERS ───────────────────────────────────────────────────────────────────
def _hash_password(plain: str) -> str:
    return bcrypt.hashpw(plain.encode(), bcrypt.gensalt()).decode()

def _verify_password(plain: str, hashed: str) -> bool:
    return bcrypt.checkpw(plain.encode(), hashed.encode())

def _create_token(email: str, name: str) -> str:
    payload = {
        "sub":  email,
        "name": name,
        "exp":  datetime.utcnow() + timedelta(hours=JWT_EXPIRE_H),
    }
    return jwt.encode(payload, JWT_SECRET, algorithm=JWT_ALGO)

def _decode_token(token: str) -> dict | None:
    try:
        return jwt.decode(token, JWT_SECRET, algorithms=[JWT_ALGO])
    except JWTError:
        return None

def get_current_user(request: Request) -> dict | None:
    """Call this from any route to get the logged-in user or None."""
    token = request.cookies.get(COOKIE_NAME)
    if not token:
        return None
    return _decode_token(token)

# ── ROUTES ────────────────────────────────────────────────────────────────────

@router.post("/signup")
async def signup(data: dict = Body(...)):
    """
    Expects: { "name": str, "email": str, "password": str }
    Returns: JSON { "ok": true } and sets session cookie
    """
    if users_col is None:
        return JSONResponse({"ok": False, "error": "Database unavailable"}, status_code=503)

    name     = (data.get("name") or "").strip()
    email    = (data.get("email") or "").strip().lower()
    password = (data.get("password") or "").strip()

    # Basic validation
    if not name or not email or not password:
        return JSONResponse({"ok": False, "error": "All fields are required"}, status_code=400)
    if len(password) < 8:
        return JSONResponse({"ok": False, "error": "Password must be at least 8 characters"}, status_code=400)
    if "@" not in email:
        return JSONResponse({"ok": False, "error": "Invalid email address"}, status_code=400)

    # Check duplicate
    if users_col.find_one({"email": email}):
        return JSONResponse({"ok": False, "error": "An account with this email already exists"}, status_code=409)

    # Store user
    users_col.insert_one({
        "name":       name,
        "email":      email,
        "password":   _hash_password(password),
        "created_at": datetime.utcnow(),
    })

    token    = _create_token(email, name)
    response = JSONResponse({"ok": True, "name": name, "email": email})
    response.set_cookie(
        key=COOKIE_NAME, value=token,
        httponly=True, samesite="lax",
        max_age=JWT_EXPIRE_H * 3600
    )
    return response


@router.post("/login")
async def login(data: dict = Body(...)):
    """
    Expects: { "email": str, "password": str }
    Returns: JSON { "ok": true } and sets session cookie
    """
    if users_col is None:
        return JSONResponse({"ok": False, "error": "Database unavailable"}, status_code=503)

    email    = (data.get("email") or "").strip().lower()
    password = (data.get("password") or "").strip()

    if not email or not password:
        return JSONResponse({"ok": False, "error": "Email and password are required"}, status_code=400)

    user = users_col.find_one({"email": email})
    if not user or not _verify_password(password, user["password"]):
        return JSONResponse({"ok": False, "error": "Invalid email or password"}, status_code=401)

    token    = _create_token(email, user["name"])
    response = JSONResponse({"ok": True, "name": user["name"], "email": email})
    response.set_cookie(
        key=COOKIE_NAME, value=token,
        httponly=True, samesite="lax",
        max_age=JWT_EXPIRE_H * 3600
    )
    return response


@router.post("/logout")
async def logout():
    """Clears the session cookie."""
    response = JSONResponse({"ok": True})
    response.delete_cookie(COOKIE_NAME)
    return response


@router.get("/me")
async def me(request: Request):
    """Returns current user info if logged in, else 401."""
    user = get_current_user(request)
    if not user:
        return JSONResponse({"ok": False, "error": "Not authenticated"}, status_code=401)
    return JSONResponse({"ok": True, "name": user["name"], "email": user["sub"]})
