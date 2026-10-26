from __future__ import annotations

from datetime import datetime
from typing import Annotated
from uuid import UUID

from pydantic import EmailStr, Field, StringConstraints, computed_field

from app.core.mailer import mail_enabled
from app.models.entities import LlmMode
from app.schemas.common import ApiModel, Country, Currency, Name, NonNegativeMinor, Timezone

Password = Annotated[str, StringConstraints(min_length=10, max_length=128)]


class RegisterRequest(ApiModel):
    email: EmailStr
    password: Password
    display_name: Name
    country: Country
    base_currency: Currency
    city: Annotated[str, StringConstraints(max_length=120)] | None = None
    address: Annotated[str, StringConstraints(max_length=500)] | None = None
    timezone: Timezone = "UTC"


class LoginRequest(ApiModel):
    email: EmailStr
    password: Annotated[str, StringConstraints(min_length=1, max_length=128)]


class TokenResponse(ApiModel):
    access_token: str
    token_type: str = "bearer"  # noqa: S105 - OAuth2 token type, not a secret
    expires_in: int


class UserRead(ApiModel):
    id: UUID
    email: str
    display_name: str
    country: str
    city: str | None
    address: str | None
    base_currency: str
    timezone: str
    reserve_months: int
    reserve_buffer_minor: int
    llm_mode: LlmMode
    llm_api_key_hint: str | None
    email_notifications: bool = False
    created_at: datetime

    @computed_field  # type: ignore[prop-decorator]
    @property
    def email_available(self) -> bool:
        """Whether this server can send email (otherwise reminders are in the app only)."""
        return mail_enabled()


class ProfileUpdate(ApiModel):
    display_name: Name | None = None
    country: Country | None = None
    city: Annotated[str, StringConstraints(max_length=120)] | None = None
    address: Annotated[str, StringConstraints(max_length=500)] | None = None
    base_currency: Currency | None = None
    timezone: Timezone | None = None
    reserve_months: Annotated[int, Field(ge=0, le=24)] | None = None
    reserve_buffer_minor: NonNegativeMinor | None = None
    email_notifications: bool | None = None


class LlmSettingsUpdate(ApiModel):
    mode: LlmMode
    api_key: Annotated[str, StringConstraints(min_length=20, max_length=256)] | None = Field(
        default=None,
        description="Required when switching to 'anthropic' without a stored key. Never returned.",
    )


class PasswordChange(ApiModel):
    current_password: Annotated[str, StringConstraints(min_length=1, max_length=128)]
    new_password: Password
