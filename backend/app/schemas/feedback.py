from __future__ import annotations

from datetime import datetime
from typing import Annotated, Any, Literal
from uuid import UUID

from pydantic import Field, StringConstraints

from app.models.entities import FeedbackKind
from app.schemas.common import ApiModel

Month = Annotated[str, StringConstraints(pattern=r"^\d{4}-(0[1-9]|1[0-2])$")]


class CommentIn(ApiModel):
    message: Annotated[str, StringConstraints(strip_whitespace=True, min_length=2, max_length=2000)]
    rating: Annotated[int, Field(ge=1, le=5)] | None = None
    page: Annotated[str, StringConstraints(max_length=120)] | None = None


class CheckinIn(ApiModel):
    month: Month
    bills_short: bool = Field(description="Ran short of money for a bill this month")
    missed_need_deadline: bool = Field(description="Missed a deadline for something needed")
    followed_plan: Literal["mostly", "partly", "no", "no_plan"]
    comment: Annotated[str, StringConstraints(strip_whitespace=True, max_length=2000)] | None = None


class CheckinDue(ApiModel):
    due: bool
    month: str  # the month the question is about, YYYY-MM


class FeedbackRead(ApiModel):
    id: UUID
    kind: FeedbackKind
    rating: int | None
    message: str | None
    page: str | None
    month: str | None
    answers: dict[str, Any] | None
    created_at: datetime
