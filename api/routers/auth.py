"""
CIPHER API — Auth routes.
POST /api/auth/login   -> JSON login for API clients, returns {access_token}
POST /auth/login        -> form login for the browser UI, sets an httpOnly cookie + redirects
GET  /auth/logout       -> clears the cookie, redirects to login page
GET  /login              -> renders the login page
"""

from fastapi import APIRouter, Depends, Form, HTTPException, Request, status
from fastapi.responses import RedirectResponse
from fastapi.templating import Jinja2Templates
from pydantic import BaseModel

from core.auth import authenticate
from api.security import create_access_token, get_current_user, COOKIE_NAME, TOKEN_EXPIRE_MINUTES

router = APIRouter()
templates = Jinja2Templates(directory="api/templates")


class LoginRequest(BaseModel):
    username: str
    password: str


class LoginResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"
    role: str
    username: str


@router.post("/api/auth/login", response_model=LoginResponse, tags=["auth"])
def api_login(payload: LoginRequest):
    """JSON login endpoint — for API clients / Postman / the /docs page."""
    user = authenticate(payload.username, payload.password)
    if user is None:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid username or password")

    token = create_access_token(user["username"], user["role"])
    return LoginResponse(access_token=token, role=user["role"], username=user["username"])


@router.get("/login", tags=["auth"])
def login_page(request: Request, error: str | None = None):
    """Renders the browser login form."""
    return templates.TemplateResponse(request, "login.html", {"error": error})


@router.post("/auth/login", tags=["auth"])
def browser_login(request: Request, username: str = Form(...), password: str = Form(...)):
    """Form submission from the login page — sets an httpOnly cookie and redirects."""
    user = authenticate(username, password)
    if user is None:
        return RedirectResponse(url="/login?error=Invalid+username+or+password", status_code=status.HTTP_303_SEE_OTHER)

    token = create_access_token(user["username"], user["role"])
    response = RedirectResponse(url="/", status_code=status.HTTP_303_SEE_OTHER)
    response.set_cookie(
        key=COOKIE_NAME,
        value=token,
        httponly=True,
        max_age=TOKEN_EXPIRE_MINUTES * 60,
        samesite="lax",
        # secure=True should be added once this runs behind HTTPS; fine as-is for local offline demo
    )
    return response


@router.get("/auth/logout", tags=["auth"])
def logout():
    response = RedirectResponse(url="/login", status_code=status.HTTP_303_SEE_OTHER)
    response.delete_cookie(COOKIE_NAME)
    return response


@router.get("/api/auth/me", tags=["auth"])
def whoami(user: dict = Depends(get_current_user)):
    """Handy for the /docs page and frontend JS — confirms the current session's identity/role."""
    return user