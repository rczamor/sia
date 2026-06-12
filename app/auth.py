from datetime import datetime, timedelta, timezone

import bcrypt
from fastapi import APIRouter, Form, HTTPException, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from jose import JWTError, jwt

from app.config import settings
from app.models.schemas import LoginRequest, TokenResponse
from app.templating import templates

router = APIRouter(tags=["auth"])

ALGORITHM = "HS256"
SESSION_COOKIE = "sia_session"


def create_token(email: str) -> str:
    expires = datetime.now(timezone.utc) + timedelta(hours=settings.jwt_expiry_hours)
    return jwt.encode({"sub": email, "exp": expires}, settings.jwt_secret, algorithm=ALGORITHM)


def verify_token(token: str) -> str:
    try:
        payload = jwt.decode(token, settings.jwt_secret, algorithms=[ALGORITHM])
        email: str = payload.get("sub", "")
        if not email:
            raise HTTPException(status_code=401, detail="Invalid token")
        return email
    except JWTError:
        raise HTTPException(status_code=401, detail="Invalid or expired token")


def verify_token_optional(token: str) -> str | None:
    """Like verify_token but returns None instead of raising (middleware use)."""
    if not token:
        return None
    try:
        payload = jwt.decode(token, settings.jwt_secret, algorithms=[ALGORITHM])
        return payload.get("sub") or None
    except JWTError:
        return None


def _check_credentials(email: str, password: str) -> bool:
    if email != settings.admin_email or not settings.admin_password_hash:
        return False
    try:
        return bcrypt.checkpw(
            password.encode()[:72], settings.admin_password_hash.encode()
        )
    except ValueError:
        return False


@router.post("/api/auth/login", response_model=TokenResponse)
async def login_api(request: LoginRequest):
    """Programmatic login: returns a bearer JWT."""
    if not settings.admin_password_hash:
        raise HTTPException(status_code=500, detail="Admin password not configured")
    if not _check_credentials(request.email, request.password):
        raise HTTPException(status_code=401, detail="Invalid credentials")
    return TokenResponse(access_token=create_token(request.email))


@router.get("/login", response_class=HTMLResponse)
async def login_page(request: Request, error: str = ""):
    return templates.TemplateResponse(request, "login.html", {"error": error})


@router.post("/login")
async def login_form(request: Request, email: str = Form(...), password: str = Form(...)):
    """Browser login: sets the HttpOnly session cookie and redirects to the admin."""
    if not _check_credentials(email, password):
        return RedirectResponse("/login?error=Invalid+credentials", status_code=303)
    response = RedirectResponse("/admin", status_code=303)
    response.set_cookie(
        SESSION_COOKIE,
        create_token(email),
        httponly=True,
        samesite="lax",
        # Secure-by-default regardless of the (proxy-dependent) request scheme;
        # see Settings.session_cookie_secure for the local-plain-http override.
        secure=settings.session_cookie_secure,
        max_age=settings.jwt_expiry_hours * 3600,
    )
    return response


@router.get("/logout")
async def logout():
    response = RedirectResponse("/login", status_code=303)
    # Deletion attributes mirror set_cookie's so the expiring Set-Cookie targets
    # the exact same cookie in every browser.
    response.delete_cookie(
        SESSION_COOKIE,
        httponly=True,
        samesite="lax",
        secure=settings.session_cookie_secure,
    )
    return response
