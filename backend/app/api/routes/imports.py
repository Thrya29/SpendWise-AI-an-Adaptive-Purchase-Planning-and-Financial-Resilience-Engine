"""Bank statement import. The statement is parsed in memory and never stored."""

from __future__ import annotations

from fastapi import APIRouter

from app.api.deps import SessionDep, UserDep, user_today
from app.core.ratelimit import enforce
from app.schemas.imports import (
    StatementApplyIn,
    StatementApplyOut,
    StatementIn,
    StatementPreviewOut,
)
from app.services import import_service

router = APIRouter(prefix="/imports", tags=["imports"])


@router.post("/statement/preview", response_model=StatementPreviewOut)
async def preview_statement(
    req: StatementIn, user: UserDep, session: SessionDep
) -> StatementPreviewOut:
    """Read a CSV/TXT bank statement and suggest recurring income and bills. Saves nothing."""
    await enforce(f"import:{user.id}", limit=20)
    return await import_service.preview(session, user, req)


@router.post("/statement/apply", response_model=StatementApplyOut)
async def apply_statement(
    req: StatementApplyIn, user: UserDep, session: SessionDep
) -> StatementApplyOut:
    """Create the confirmed income and bills, and optionally set the account balance."""
    return await import_service.apply(session, user, req, user_today(user))
