from __future__ import annotations

from typing import Annotated, Any

from fastapi import APIRouter, status
from pydantic import BaseModel, StringConstraints
from sqlalchemy import delete, select

from app.api.deps import SessionDep, UserDep
from app.core.errors import DomainValidationError, UnauthorizedError
from app.core.security import encrypt_secret, verify_password
from app.models.entities import (
    Account,
    AuditEvent,
    IncomeStream,
    LlmMode,
    Obligation,
    PlannedItem,
    Transaction,
    User,
)
from app.schemas.finance import (
    AccountRead,
    IncomeRead,
    ObligationRead,
    PlannedItemRead,
    TransactionRead,
)
from app.schemas.users import LlmSettingsUpdate, ProfileUpdate, UserRead

router = APIRouter(prefix="/me", tags=["profile"])


class DeleteAccountRequest(BaseModel):
    password: Annotated[str, StringConstraints(min_length=1, max_length=128)]


@router.get("", response_model=UserRead)
async def read_me(user: UserDep) -> UserRead:
    return UserRead.model_validate(user)


@router.patch("", response_model=UserRead)
async def update_me(body: ProfileUpdate, user: UserDep, session: SessionDep) -> UserRead:
    for key, value in body.model_dump(exclude_unset=True).items():
        if value is None and key in {
            "display_name",
            "country",
            "base_currency",
            "timezone",
            "reserve_months",
            "reserve_buffer_minor",
            "email_notifications",
        }:
            raise DomainValidationError(f"{key} cannot be null")
        setattr(user, key, value)
    await session.flush()
    return UserRead.model_validate(user)


@router.put("/llm", response_model=UserRead)
async def update_llm_settings(
    body: LlmSettingsUpdate, user: UserDep, session: SessionDep
) -> UserRead:
    """Choose between the built-in mock assistant and your own Anthropic API key."""
    if body.api_key is not None:
        key = body.api_key.strip()
        if not key.startswith("sk-ant-"):
            raise DomainValidationError("That does not look like an Anthropic API key (sk-ant-...)")
        user.llm_api_key_encrypted = encrypt_secret(key)
        user.llm_api_key_hint = key[-4:]
    if body.mode is LlmMode.ANTHROPIC and user.llm_api_key_encrypted is None:
        raise DomainValidationError("Provide an API key to use the Anthropic provider")
    user.llm_mode = body.mode
    await session.flush()
    return UserRead.model_validate(user)


@router.delete("/llm/key", response_model=UserRead)
async def delete_llm_key(user: UserDep, session: SessionDep) -> UserRead:
    user.llm_api_key_encrypted = None
    user.llm_api_key_hint = None
    user.llm_mode = LlmMode.MOCK
    await session.flush()
    return UserRead.model_validate(user)


@router.get("/export")
async def export_my_data(user: UserDep, session: SessionDep) -> dict[str, Any]:
    """Machine-readable export of everything stored about the user (data portability)."""

    async def dump(model: type[Any], schema: type[BaseModel]) -> list[dict[str, Any]]:
        rows = await session.scalars(select(model).where(model.user_id == user.id))
        return [schema.model_validate(r).model_dump(mode="json") for r in rows]

    return {
        "profile": UserRead.model_validate(user).model_dump(mode="json"),
        "accounts": await dump(Account, AccountRead),
        "income_streams": await dump(IncomeStream, IncomeRead),
        "obligations": await dump(Obligation, ObligationRead),
        "planned_items": await dump(PlannedItem, PlannedItemRead),
        "transactions": await dump(Transaction, TransactionRead),
    }


@router.post("/delete", status_code=status.HTTP_204_NO_CONTENT)
async def delete_my_account(body: DeleteAccountRequest, user: UserDep, session: SessionDep) -> None:
    """Permanently erase the account and all associated data."""
    if not verify_password(body.password, user.password_hash):
        raise UnauthorizedError("Password is incorrect")
    await session.execute(delete(AuditEvent).where(AuditEvent.user_id == user.id))
    await session.execute(delete(User).where(User.id == user.id))
