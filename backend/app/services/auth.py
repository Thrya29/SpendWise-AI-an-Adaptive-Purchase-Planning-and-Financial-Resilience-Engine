"""Registration, login and rotating refresh tokens with reuse detection."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from uuid import UUID, uuid4

from sqlalchemy import select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import get_settings
from app.core.db import utcnow
from app.core.errors import ConflictError, UnauthorizedError
from app.core.security import (
    create_access_token,
    hash_password,
    hash_refresh_token,
    new_refresh_token,
    verify_password,
)
from app.models.entities import RefreshToken, User
from app.schemas.users import RegisterRequest


@dataclass(frozen=True, slots=True)
class IssuedTokens:
    access_token: str
    refresh_token: str
    expires_in: int


def _aware(value: datetime) -> datetime:
    # SQLite drops tzinfo; PostgreSQL keeps it. Normalise to UTC either way.
    return value if value.tzinfo else value.replace(tzinfo=UTC)


async def register(session: AsyncSession, data: RegisterRequest) -> User:
    email = data.email.lower()
    if await session.scalar(select(User.id).where(User.email == email)):
        raise ConflictError("An account with this email already exists")
    user = User(
        email=email,
        password_hash=hash_password(data.password),
        display_name=data.display_name,
        country=data.country,
        city=data.city,
        address=data.address,
        base_currency=data.base_currency,
        timezone=data.timezone,
    )
    session.add(user)
    try:
        await session.flush()
    except IntegrityError as exc:  # concurrent registration race
        raise ConflictError("An account with this email already exists") from exc
    return user


async def authenticate(session: AsyncSession, email: str, password: str) -> User:
    user = await session.scalar(select(User).where(User.email == email.lower()))
    if not verify_password(password, user.password_hash if user else None) or user is None:
        raise UnauthorizedError("Invalid email or password")
    return user


async def issue_tokens(
    session: AsyncSession, user_id: UUID, family_id: UUID | None = None
) -> IssuedTokens:
    s = get_settings()
    raw, digest = new_refresh_token()
    session.add(
        RefreshToken(
            user_id=user_id,
            token_hash=digest,
            family_id=family_id or uuid4(),
            expires_at=utcnow() + timedelta(days=s.refresh_token_days),
        )
    )
    await session.flush()
    return IssuedTokens(create_access_token(user_id), raw, s.access_token_minutes * 60)


async def rotate(session: AsyncSession, raw_refresh: str) -> IssuedTokens:
    token = await session.scalar(
        select(RefreshToken).where(RefreshToken.token_hash == hash_refresh_token(raw_refresh))
    )
    if token is None:
        raise UnauthorizedError("Session expired. Please sign in again.")
    now = utcnow()
    if token.revoked_at is not None:
        # Reuse of a rotated token: assume theft and revoke the whole family.
        # Commit first: the error below rolls back the request transaction.
        await revoke_family(session, token.family_id)
        await session.commit()
        raise UnauthorizedError("Session expired. Please sign in again.")
    if _aware(token.expires_at) <= now:
        raise UnauthorizedError("Session expired. Please sign in again.")
    token.revoked_at = now
    return await issue_tokens(session, token.user_id, token.family_id)


async def revoke_family(session: AsyncSession, family_id: UUID) -> None:
    await session.execute(
        update(RefreshToken)
        .where(RefreshToken.family_id == family_id, RefreshToken.revoked_at.is_(None))
        .values(revoked_at=utcnow())
    )


async def revoke(session: AsyncSession, raw_refresh: str) -> None:
    token = await session.scalar(
        select(RefreshToken).where(RefreshToken.token_hash == hash_refresh_token(raw_refresh))
    )
    if token is not None:
        await revoke_family(session, token.family_id)


async def revoke_all_for_user(session: AsyncSession, user_id: UUID) -> None:
    await session.execute(
        update(RefreshToken)
        .where(RefreshToken.user_id == user_id, RefreshToken.revoked_at.is_(None))
        .values(revoked_at=utcnow())
    )
