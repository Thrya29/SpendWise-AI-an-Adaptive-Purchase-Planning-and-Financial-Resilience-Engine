"""Provider selection with graceful fallback to the built-in assistant."""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Protocol

from app.ai.anthropic_provider import AnthropicAssistant, AssistantUnavailableError, RawAlternative
from app.ai.mock import MockAssistant
from app.ai.schemas import ParseContext, PlanFacts, RawItemDraft
from app.core.security import decrypt_secret
from app.models.entities import LlmMode, User

logger = logging.getLogger("spendwise.ai")


class Assistant(Protocol):
    name: str

    async def parse_item(self, text: str, ctx: ParseContext) -> RawItemDraft: ...

    async def summarize_plan(self, facts: PlanFacts) -> str: ...


@dataclass(frozen=True, slots=True)
class AssistantResult[T]:
    value: T
    source: str  # "mock" | "anthropic"
    notice: str | None = None  # why we fell back, if we did


def _assistant_for(user: User) -> tuple[Assistant, str | None]:
    if user.llm_mode is LlmMode.ANTHROPIC and user.llm_api_key_encrypted:
        key = decrypt_secret(user.llm_api_key_encrypted)
        if key:
            return AnthropicAssistant(key), None
        return MockAssistant(), "Your saved API key could not be read. Please enter it again."
    return MockAssistant(), None


async def parse_item(user: User, text: str, ctx: ParseContext) -> AssistantResult[RawItemDraft]:
    primary, notice = _assistant_for(user)
    if isinstance(primary, AnthropicAssistant):
        try:
            return AssistantResult(await primary.parse_item(text, ctx), primary.name)
        except AssistantUnavailableError as exc:
            notice = f"{exc.reason} Used the built-in assistant instead."
    return AssistantResult(await MockAssistant().parse_item(text, ctx), "mock", notice)


async def summarize_plan(user: User, facts: PlanFacts) -> AssistantResult[str]:
    primary, notice = _assistant_for(user)
    if isinstance(primary, AnthropicAssistant):
        try:
            return AssistantResult(await primary.summarize_plan(facts), primary.name)
        except AssistantUnavailableError as exc:
            notice = f"{exc.reason} Used the built-in summary instead."
    return AssistantResult(await MockAssistant().summarize_plan(facts), "mock", notice)


async def find_alternatives(
    user: User, *, name: str, kind: str, country: str, budget: str
) -> tuple[list[RawAlternative], int, str]:
    """(verified suggestions, dropped count, message). Requires the user's Claude key."""
    primary, notice = _assistant_for(user)
    if not isinstance(primary, AnthropicAssistant):
        return (
            [],
            0,
            notice
            or (
                "Finding alternatives needs a live web search, which uses your own Claude API key. "
                "Add one in Settings, or add alternatives yourself."
            ),
        )
    try:
        found, dropped = await primary.find_alternatives(
            name=name, kind=kind, country=country, budget=budget
        )
    except AssistantUnavailableError as exc:
        return [], 0, exc.reason
    if not found:
        return [], dropped, "No current alternatives could be verified from the search results."
    note = f" {dropped} unverified suggestion(s) were removed." if dropped else ""
    return found, dropped, f"Found {len(found)} alternative(s) from current web pages.{note}"
