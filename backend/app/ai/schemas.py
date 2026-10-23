"""Shapes exchanged with assistant providers. Amounts are decimal *strings*, never floats."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

TierLit = Literal["need", "want", "desire"]
KindLit = Literal["product", "service", "travel", "experience", "subscription", "other"]
DeadlineLit = Literal["hard", "soft", "none"]


class RawItemDraft(BaseModel):
    """What a provider extracts from free text. Every field may be absent."""

    model_config = ConfigDict(extra="forbid")

    name: str = Field(min_length=1, max_length=200)
    tier: TierLit | None = None
    kind: KindLit | None = None
    priority: int | None = Field(default=None, ge=1, le=5)
    amount: str | None = Field(
        default=None,
        pattern=r"^\d{1,13}(\.\d{1,3})?$",
        description="Price per unit in major units as a plain decimal string, "
        "e.g. '1500' or '74999.50'",
    )
    currency: str | None = Field(default=None, pattern=r"^[A-Z]{3}$")
    quantity: int | None = Field(default=None, ge=1, le=1000)
    target_date: date | None = None
    deadline_type: DeadlineLit | None = None
    location: str | None = Field(default=None, max_length=200)


@dataclass(frozen=True, slots=True)
class ParseContext:
    today: date
    base_currency: str
    city: str | None = None


@dataclass(frozen=True, slots=True)
class PlanFacts:
    """Engine-computed facts a summary may use. Summaries may not introduce other numbers."""

    currency: str
    horizon_months: int
    scenario_names: list[str]
    buy_now: list[str]
    scheduled: list[tuple[str, str]]  # (name, "15 Jan 2027")
    postponed: list[tuple[str, str]]  # (name, formatted shortfall)
    waiting_for_price: list[str]
    using_reserve: list[str]
    late: list[str]
    total_planned: str  # formatted
    reserve: str  # formatted
    lowest_balance: list[tuple[str, str]]  # (scenario, formatted)
    reserve_zero: bool = False  # no emergency reserve configured
    # Scenarios whose balance breaks the reserve even if nothing is bought.
    unsafe_anyway: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)

    def as_text(self) -> str:
        lines = [
            f"Currency: {self.currency}. Horizon: {self.horizon_months} months.",
            f"Protected scenarios: {', '.join(self.scenario_names)}.",
            f"Emergency reserve kept: {self.reserve}. "
            f"Total planned spending: {self.total_planned}.",
            f"Buy now: {', '.join(self.buy_now) or 'none'}.",
            "Scheduled: " + ("; ".join(f"{n} on {d}" for n, d in self.scheduled) or "none") + ".",
            "Postponed: "
            + ("; ".join(f"{n} (needs {s} more headroom)" for n, s in self.postponed) or "none")
            + ".",
            f"Waiting for a lower price: {', '.join(self.waiting_for_price) or 'none'}.",
            f"Needs your approval to use the reserve: {', '.join(self.using_reserve) or 'none'}.",
            f"Later than the target date: {', '.join(self.late) or 'none'}.",
            "Lowest balance: " + "; ".join(f"{s}: {v}" for s, v in self.lowest_balance) + ".",
            "Below the reserve even with no purchases: "
            + (", ".join(self.unsafe_anyway) or "none")
            + ".",
        ]
        lines += [f"Warning: {w}" for w in self.warnings]
        return "\n".join(lines)
