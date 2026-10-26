from __future__ import annotations

from datetime import date, datetime
from typing import Annotated
from zoneinfo import ZoneInfo

from fastapi import Depends, Query
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import get_settings
from app.core.db import get_session
from app.core.errors import UnauthorizedError
from app.core.security import decode_access_token
from app.models.entities import User
from app.services import usage

_bearer = HTTPBearer(auto_error=False)

SessionDep = Annotated[AsyncSession, Depends(get_session)]


async def current_user(
    session: SessionDep,
    creds: Annotated[HTTPAuthorizationCredentials | None, Depends(_bearer)],
) -> User:
    if creds is None or creds.scheme.lower() != "bearer":
        raise UnauthorizedError("Authentication required")
    user_id = decode_access_token(creds.credentials)
    user = await session.get(User, user_id) if user_id else None
    if user is None:
        raise UnauthorizedError("Invalid or expired access token")
    usage.mark_active(session, user, user_today(user))
    return user


UserDep = Annotated[User, Depends(current_user)]


def user_today(user: User) -> date:
    return datetime.now(ZoneInfo(user.timezone)).date()


class Paging:
    def __init__(
        self,
        limit: Annotated[int, Query(ge=1)] = 50,
        offset: Annotated[int, Query(ge=0)] = 0,
    ) -> None:
        self.limit = min(limit, get_settings().max_page_size)
        self.offset = offset


PagingDep = Annotated[Paging, Depends()]
