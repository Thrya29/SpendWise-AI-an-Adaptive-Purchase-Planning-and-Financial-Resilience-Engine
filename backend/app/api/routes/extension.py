"""Endpoints for the browser extension. They accept only extension keys, and only list items
and save a price the user confirmed on a product page."""

from __future__ import annotations

from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, Header, status
from sqlalchemy import select

from app.api.deps import SessionDep, UserDep
from app.core.errors import UnauthorizedError
from app.core.ratelimit import enforce
from app.models.entities import ExtensionToken, ItemStatus, PlannedItem, User
from app.schemas.extension import (
    CaptureIn,
    CaptureOut,
    ExtensionItemOut,
    ExtensionTokenCreated,
    ExtensionTokenIn,
    ExtensionTokenOut,
)
from app.services import extension_service
from app.services.repository import OwnedRepository

router = APIRouter(prefix="/extension", tags=["browser extension"])
keys_router = APIRouter(prefix="/me/extension-keys", tags=["browser extension"])


async def extension_user(
    session: SessionDep, authorization: Annotated[str | None, Header()] = None
) -> User:
    scheme, _, raw = (authorization or "").partition(" ")
    if scheme.lower() != "bearer" or not raw:
        raise UnauthorizedError("Extension key required")
    return await extension_service.user_for_token(session, raw.strip())


ExtensionUser = Annotated[User, Depends(extension_user)]


@router.get("/items", response_model=list[ExtensionItemOut])
async def list_items(user: ExtensionUser, session: SessionDep) -> list[ExtensionItemOut]:
    """Items still being planned, to attach a price to."""
    await enforce(f"extension:{user.id}", limit=60)
    rows = await session.scalars(
        select(PlannedItem)
        .where(
            PlannedItem.user_id == user.id,
            PlannedItem.status.in_([ItemStatus.PLANNED, ItemStatus.POSTPONED]),
        )
        .order_by(PlannedItem.name)
        .limit(300)
    )
    return [ExtensionItemOut.model_validate(r) for r in rows]


@router.post("/capture", response_model=CaptureOut, status_code=status.HTTP_201_CREATED)
async def capture(req: CaptureIn, user: ExtensionUser, session: SessionDep) -> CaptureOut:
    """Save a price the user saw on a product page and confirmed."""
    await enforce(f"extension:{user.id}", limit=60)
    return await extension_service.capture(session, user, req)


@keys_router.get("", response_model=list[ExtensionTokenOut])
async def list_keys(user: UserDep, session: SessionDep) -> list[ExtensionTokenOut]:
    rows = await session.scalars(
        select(ExtensionToken)
        .where(ExtensionToken.user_id == user.id)
        .order_by(ExtensionToken.created_at)
    )
    return [ExtensionTokenOut.model_validate(r) for r in rows]


@keys_router.post("", response_model=ExtensionTokenCreated, status_code=status.HTTP_201_CREATED)
async def create_key(
    body: ExtensionTokenIn, user: UserDep, session: SessionDep
) -> ExtensionTokenCreated:
    await enforce(f"extension-keys:{user.id}", limit=10, window_seconds=3600)
    token, raw = await extension_service.create_token(session, user, body.label)
    return ExtensionTokenCreated(**ExtensionTokenOut.model_validate(token).model_dump(), token=raw)


@keys_router.delete("/{key_id}", status_code=status.HTTP_204_NO_CONTENT)
async def revoke_key(key_id: UUID, user: UserDep, session: SessionDep) -> None:
    """Revoke a key immediately; the extension stops working until a new key is entered."""
    await OwnedRepository(session, ExtensionToken, user.id).delete(key_id)
