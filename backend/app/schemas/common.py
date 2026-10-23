from __future__ import annotations

from typing import Annotated, Generic, TypeVar
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from pydantic import AfterValidator, BaseModel, ConfigDict, Field, StringConstraints

from app.domain.money import validate_currency

T = TypeVar("T")


def _tz(value: str) -> str:
    try:
        ZoneInfo(value)
    except (ZoneInfoNotFoundError, ValueError) as exc:
        raise ValueError(f"Unknown timezone: {value}") from exc
    return value


Currency = Annotated[str, AfterValidator(validate_currency)]
Country = Annotated[str, StringConstraints(pattern=r"^[A-Za-z]{2}$", to_upper=True)]
Timezone = Annotated[str, AfterValidator(_tz)]
Name = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=100)]
PositiveMinor = Annotated[int, Field(gt=0, le=10**15)]
NonNegativeMinor = Annotated[int, Field(ge=0, le=10**15)]
SignedMinor = Annotated[int, Field(ge=-(10**15), le=10**15)]


class ApiModel(BaseModel):
    model_config = ConfigDict(from_attributes=True, extra="forbid", str_strip_whitespace=True)


class Page(BaseModel, Generic[T]):
    items: list[T]
    total: int
    limit: int
    offset: int
