"""Factory for owner-scoped CRUD routers with consistent semantics.

GET    /{name}           paginated list (optionally filtered)
POST   /{name}           create
GET    /{name}/{id}      read
PATCH  /{name}/{id}      partial update; body must carry the current ``version``
DELETE /{name}/{id}      delete
"""

from collections.abc import Awaitable, Callable, Sequence
from typing import Any
from uuid import UUID

from fastapi import APIRouter, Depends, status
from pydantic import BaseModel
from sqlalchemy import ColumnElement
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import PagingDep, SessionDep, UserDep
from app.core.errors import DomainValidationError
from app.models.entities import User
from app.schemas.common import Page
from app.services.repository import OwnedRepository

Hook = Callable[[AsyncSession, User, dict[str, Any], Any | None], Awaitable[dict[str, Any]]]
Serializer = Callable[[AsyncSession, User, Sequence[Any]], Awaitable[list[BaseModel]]]


async def _no_hook(
    _s: AsyncSession, _u: User, values: dict[str, Any], _obj: Any | None
) -> dict[str, Any]:
    return values


def build_crud_router(
    *,
    name: str,
    tag: str,
    model: type[Any],
    create_schema: type[BaseModel],
    update_schema: type[BaseModel],
    read_schema: type[BaseModel],
    filters_dep: Callable[..., Sequence[ColumnElement[bool]]] | None = None,
    order_by: Callable[[], Sequence[Any]] = lambda: (),
    before_write: Hook = _no_hook,
    serialize: Serializer | None = None,
    non_nullable: frozenset[str] = frozenset(),
) -> APIRouter:
    router = APIRouter(prefix=f"/{name}", tags=[tag])

    async def to_read(session: AsyncSession, user: User, rows: Sequence[Any]) -> list[BaseModel]:
        if serialize is not None:
            return await serialize(session, user, rows)
        return [read_schema.model_validate(r) for r in rows]

    def no_filters() -> Sequence[ColumnElement[bool]]:
        return ()

    filters_provider = filters_dep or no_filters

    @router.get("", response_model=Page[read_schema])  # type: ignore[valid-type]
    async def list_rows(
        user: UserDep,
        session: SessionDep,
        paging: PagingDep,
        filters: Sequence[ColumnElement[bool]] = Depends(filters_provider),
    ) -> dict[str, Any]:
        repo = OwnedRepository(session, model, user.id)
        rows, total = await repo.page(
            filters=filters, order_by=order_by(), limit=paging.limit, offset=paging.offset
        )
        return {
            "items": await to_read(session, user, rows),
            "total": total,
            "limit": paging.limit,
            "offset": paging.offset,
        }

    @router.post("", response_model=read_schema, status_code=status.HTTP_201_CREATED)
    async def create_row(body: create_schema, user: UserDep, session: SessionDep) -> BaseModel:  # type: ignore[valid-type]
        values = await before_write(session, user, body.model_dump(mode="python"), None)  # type: ignore[attr-defined]
        obj = await OwnedRepository(session, model, user.id).create(**values)
        return (await to_read(session, user, [obj]))[0]

    @router.get("/{obj_id}", response_model=read_schema)
    async def read_row(obj_id: UUID, user: UserDep, session: SessionDep) -> BaseModel:
        obj = await OwnedRepository(session, model, user.id).get(obj_id)
        return (await to_read(session, user, [obj]))[0]

    @router.patch("/{obj_id}", response_model=read_schema)
    async def update_row(
        obj_id: UUID,
        body: update_schema,  # type: ignore[valid-type]
        user: UserDep,
        session: SessionDep,
    ) -> BaseModel:
        repo = OwnedRepository(session, model, user.id)
        changes = body.model_dump(mode="python", exclude_unset=True)  # type: ignore[attr-defined]
        version = changes.pop("version")
        for key in non_nullable & {k for k, v in changes.items() if v is None}:
            raise DomainValidationError(f"{key} cannot be null")
        current = await repo.get(obj_id)
        changes = await before_write(session, user, changes, current)
        obj = await repo.update(obj_id, version, changes)
        return (await to_read(session, user, [obj]))[0]

    @router.delete("/{obj_id}", status_code=status.HTTP_204_NO_CONTENT)
    async def delete_row(obj_id: UUID, user: UserDep, session: SessionDep) -> None:
        await OwnedRepository(session, model, user.id).delete(obj_id)

    return router
