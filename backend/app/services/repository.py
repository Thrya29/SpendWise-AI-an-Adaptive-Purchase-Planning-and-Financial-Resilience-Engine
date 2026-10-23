"""Owner-scoped CRUD with optimistic concurrency and an audit trail.

Every query is filtered by ``user_id``; a row owned by another user is
indistinguishable from a missing row (404), so IDs cannot be probed.
"""

from __future__ import annotations

from collections.abc import Sequence
from datetime import date, datetime
from enum import Enum
from typing import Any, Generic, TypeVar
from uuid import UUID

from sqlalchemy import ColumnElement, Select, func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm.exc import StaleDataError

from app.core.db import Base
from app.core.errors import ConflictError, NotFoundError
from app.models.entities import AuditEvent

M = TypeVar("M", bound=Base)

_STALE = "This record was changed elsewhere. Reload and try again."


def _jsonable(value: Any) -> Any:
    if isinstance(value, Enum):
        return value.value
    if isinstance(value, date | datetime | UUID):
        return str(value)
    return value


class OwnedRepository(Generic[M]):
    def __init__(self, session: AsyncSession, model: type[M], user_id: UUID) -> None:
        self.session = session
        self.model = model
        self.user_id = user_id
        self.entity: str = model.__tablename__
        self._owner_col: Any = model.user_id  # type: ignore[attr-defined]
        self._id_col: Any = model.id  # type: ignore[attr-defined]

    def _base(self) -> Select[M]:
        return select(self.model).where(self._owner_col == self.user_id)

    async def page(
        self,
        *,
        filters: Sequence[ColumnElement[bool]] = (),
        order_by: Sequence[Any] = (),
        limit: int = 50,
        offset: int = 0,
    ) -> tuple[list[M], int]:
        query = self._base().where(*filters)
        total = await self.session.scalar(select(func.count()).select_from(query.subquery()))
        rows = await self.session.scalars(query.order_by(*order_by).limit(limit).offset(offset))
        return list(rows), int(total or 0)

    async def get(self, obj_id: UUID) -> M:
        obj = await self.session.scalar(self._base().where(self._id_col == obj_id))
        if obj is None:
            raise NotFoundError(f"{self.entity.rstrip('s').replace('_', ' ')} not found")
        return obj

    async def create(self, **values: Any) -> M:
        obj = self.model(user_id=self.user_id, **values)
        self.session.add(obj)
        await self.session.flush()
        await self._audit(obj, "create", {k: _jsonable(v) for k, v in values.items()})
        return obj

    async def update(self, obj_id: UUID, version: int, changes: dict[str, Any]) -> M:
        obj = await self.get(obj_id)
        current_version: int = getattr(obj, "version")  # noqa: B009
        if current_version != version:
            raise ConflictError(_STALE, extra={"current_version": current_version})
        diff: dict[str, Any] = {}
        for key, value in changes.items():
            old = getattr(obj, key)
            if old != value:
                diff[key] = {"from": _jsonable(old), "to": _jsonable(value)}
                setattr(obj, key, value)
        if diff:
            try:
                await self.session.flush()
            except StaleDataError as exc:
                raise ConflictError(_STALE) from exc
            await self._audit(obj, "update", diff)
        return obj

    async def delete(self, obj_id: UUID) -> None:
        obj = await self.get(obj_id)
        await self.session.delete(obj)
        await self._audit(obj, "delete", {})
        await self.session.flush()

    async def _audit(self, obj: M, action: str, changes: dict[str, Any]) -> None:
        self.session.add(
            AuditEvent(
                user_id=self.user_id,
                entity=self.entity,
                entity_id=getattr(obj, "id"),  # noqa: B009
                action=action,
                changes=changes,
            )
        )
