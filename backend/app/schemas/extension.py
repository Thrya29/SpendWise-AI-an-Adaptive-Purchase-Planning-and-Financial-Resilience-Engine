from __future__ import annotations

from datetime import datetime
from typing import Annotated, Self
from uuid import UUID

from pydantic import AnyHttpUrl, Field, StringConstraints, model_validator

from app.models.entities import Availability, ItemKind, Tier
from app.schemas.common import ApiModel, Currency, Name, PositiveMinor

Label = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=60)]


class ExtensionTokenIn(ApiModel):
    label: Label = "Browser extension"


class ExtensionTokenOut(ApiModel):
    id: UUID
    label: str
    hint: str
    created_at: datetime
    last_used_at: datetime | None


class ExtensionTokenCreated(ExtensionTokenOut):
    token: str = Field(description="Shown once. Paste it into the extension; it is not stored.")


class ExtensionItemOut(ApiModel):
    id: UUID
    name: str
    tier: Tier
    estimated_price_minor: int
    currency: str
    url: str | None


class NewItemIn(ApiModel):
    name: Name
    tier: Tier = Tier.WANT
    priority: Annotated[int, Field(ge=1, le=5)] = 3
    kind: ItemKind = ItemKind.PRODUCT


class CaptureIn(ApiModel):
    url: AnyHttpUrl
    page_title: Annotated[str, StringConstraints(strip_whitespace=True, max_length=300)] | None = (
        None
    )
    price_minor: PositiveMinor
    currency: Currency
    availability: Availability = Availability.UNKNOWN
    item_id: UUID | None = Field(default=None, description="Save the price to this item...")
    new_item: NewItemIn | None = Field(default=None, description="...or create a new item")
    use_price: bool = Field(default=True, description="Also make it the item's planning price")

    @model_validator(mode="after")
    def _one_target(self) -> Self:
        if (self.item_id is None) == (self.new_item is None):
            raise ValueError("Give either item_id or new_item")
        if self.url.scheme not in {"http", "https"}:
            raise ValueError("Only http and https pages can be saved")
        return self


class CaptureOut(ApiModel):
    item_id: UUID
    item_name: str
    observation_id: UUID
    created_item: bool
    price_applied: bool
    alerts: list[str]
