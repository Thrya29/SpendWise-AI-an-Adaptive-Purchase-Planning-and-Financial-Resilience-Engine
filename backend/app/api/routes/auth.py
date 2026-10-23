from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Cookie, Request, Response, status

from app.api.deps import SessionDep, UserDep
from app.core.config import get_settings
from app.core.errors import UnauthorizedError
from app.core.ratelimit import enforce
from app.core.security import hash_password, verify_password
from app.schemas.users import (
    LoginRequest,
    PasswordChange,
    RegisterRequest,
    TokenResponse,
    UserRead,
)
from app.services import auth as auth_service
from app.services.auth import IssuedTokens

router = APIRouter(prefix="/auth", tags=["auth"])

REFRESH_COOKIE = "sw_refresh"
COOKIE_PATH = "/api/v1/auth"


def _client_ip(request: Request) -> str:
    return request.client.host if request.client else "unknown"


def _set_refresh_cookie(response: Response, tokens: IssuedTokens) -> TokenResponse:
    s = get_settings()
    response.set_cookie(
        REFRESH_COOKIE,
        tokens.refresh_token,
        max_age=s.refresh_token_days * 86400,
        httponly=True,
        secure=s.cookie_secure,
        samesite="strict",
        path=COOKIE_PATH,
    )
    return TokenResponse(access_token=tokens.access_token, expires_in=tokens.expires_in)


@router.post("/register", response_model=UserRead, status_code=status.HTTP_201_CREATED)
async def register(body: RegisterRequest, request: Request, session: SessionDep) -> UserRead:
    await enforce(f"register:{_client_ip(request)}", get_settings().login_rate_limit_per_minute)
    user = await auth_service.register(session, body)
    return UserRead.model_validate(user)


@router.post("/login", response_model=TokenResponse)
async def login(
    body: LoginRequest, request: Request, response: Response, session: SessionDep
) -> TokenResponse:
    limit = get_settings().login_rate_limit_per_minute
    await enforce(f"login:ip:{_client_ip(request)}", limit)
    await enforce(f"login:email:{body.email.lower()}", limit)
    user = await auth_service.authenticate(session, body.email, body.password)
    tokens = await auth_service.issue_tokens(session, user.id)
    return _set_refresh_cookie(response, tokens)


@router.post("/refresh", response_model=TokenResponse)
async def refresh(
    response: Response,
    session: SessionDep,
    sw_refresh: Annotated[str | None, Cookie()] = None,
) -> TokenResponse:
    if not sw_refresh:
        raise UnauthorizedError("Session expired. Please sign in again.")
    tokens = await auth_service.rotate(session, sw_refresh)
    return _set_refresh_cookie(response, tokens)


@router.post("/logout", status_code=status.HTTP_204_NO_CONTENT)
async def logout(
    response: Response,
    session: SessionDep,
    sw_refresh: Annotated[str | None, Cookie()] = None,
) -> None:
    if sw_refresh:
        await auth_service.revoke(session, sw_refresh)
    response.delete_cookie(REFRESH_COOKIE, path=COOKIE_PATH)


@router.post("/password", status_code=status.HTTP_204_NO_CONTENT)
async def change_password(body: PasswordChange, user: UserDep, session: SessionDep) -> None:
    if not verify_password(body.current_password, user.password_hash):
        raise UnauthorizedError("Current password is incorrect")
    user.password_hash = hash_password(body.new_password)
    await auth_service.revoke_all_for_user(session, user.id)
