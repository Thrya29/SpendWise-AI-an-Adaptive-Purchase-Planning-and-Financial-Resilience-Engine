import json
from datetime import date
from types import SimpleNamespace
from typing import Any

import anthropic
import httpx
import pytest

from app.ai import service
from app.ai.anthropic_provider import AnthropicAssistant, AssistantUnavailableError
from app.ai.formatting import format_amount
from app.ai.mock import MockAssistant
from app.ai.schemas import ParseContext, PlanFacts
from app.core.security import encrypt_secret
from app.models.entities import LlmMode, User

CTX = ParseContext(today=date(2026, 10, 23), base_currency="INR", city="Pune")


async def parse(text: str):
    return await MockAssistant().parse_item(text, CTX)


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("salon visit next month around ₹1,500",
         {"name": "Salon visit", "kind": "service", "amount": "1500", "currency": "INR",
          "target_date": date(2026, 11, 23), "deadline_type": "soft"}),
        ("Work laptop for 75k by 15 Dec, must have",
         {"name": "Work laptop", "tier": "need", "amount": "75000",
          "target_date": date(2026, 12, 15), "deadline_type": "hard"}),
        ("trip to Goa in March, budget 40000",
         {"name": "Trip to Goa", "kind": "travel", "amount": "40000",
          "target_date": date(2027, 3, 31)}),
        ("2 tickets for the Coldplay concert $150",
         {"kind": "experience", "tier": "desire", "amount": "150", "currency": "USD",
          "quantity": 2}),
        ("new phone 1.2 lakh maybe someday",
         {"name": "New phone", "amount": "120000", "priority": 2, "deadline_type": "none"}),
        ("urgent dentist checkup tomorrow 2500 rs",
         {"name": "Dentist checkup", "tier": "need", "priority": 5, "amount": "2500",
          "target_date": date(2026, 10, 24)}),
        ("Netflix subscription 649", {"kind": "subscription", "amount": "649"}),
        ("gym membership at Cult Fit for 12000 next week",
         {"location": "Cult Fit", "target_date": date(2026, 10, 30), "amount": "12000"}),
        ("birthday gift", {"name": "Birthday gift", "amount": None, "target_date": None}),
        ("pay school fees 2026-11-05 ₹18,500.50",
         {"tier": "need", "amount": "18500.5", "target_date": date(2026, 11, 5)}),
        ("anniversary dinner on Jan 4 for 6000",
         {"kind": "experience", "amount": "6000", "target_date": date(2027, 1, 4)}),
        ("monitor in 3 weeks 1.5k", {"amount": "1500", "target_date": date(2026, 11, 13)}),
        ("car service 1 crore", {"amount": "10000000", "kind": "service"}),
    ],
)  # fmt: skip
async def test_mock_parser(text: str, expected: dict[str, Any]) -> None:
    draft = await parse(text)
    for key, value in expected.items():
        assert getattr(draft, key) == value, (key, draft)


async def test_mock_parser_ignores_years_and_handles_relative_phrases() -> None:
    d = await parse("vacation in 2027")
    assert d.amount is None and d.tier == "desire"
    assert (await parse("haircut this weekend")).target_date == date(2026, 10, 24)
    assert (await parse("rent end of month 25000")).target_date == date(2026, 10, 31)
    assert (await parse("shoes next friday")).target_date == date(2026, 10, 30)
    assert (await parse("bag in 2 months")).target_date == date(2026, 12, 23)
    assert (await parse("x")).name == "X"


def facts(**kw: Any) -> PlanFacts:
    base: dict[str, Any] = {
        "currency": "INR", "horizon_months": 6,
        "scenario_names": ["As expected", "Salary delayed 2 months"],
        "buy_now": ["Headphones"], "scheduled": [("Laptop", "2 Jan 2027")],
        "postponed": [("Trip", "₹20,000")], "waiting_for_price": [], "using_reserve": [],
        "late": ["Laptop"], "total_planned": "₹80,000", "reserve": "₹40,000",
        "lowest_balance": [("As expected", "₹45,000")],
    }  # fmt: skip
    base.update(kw)
    return PlanFacts(**base)


async def test_mock_summary_mentions_every_decision_group() -> None:
    text = await MockAssistant().summarize_plan(facts(using_reserve=["Surgery"]))
    for fragment in ("Headphones", "Laptop on 2 Jan 2027", "Trip (needs ₹20,000", "Surgery",
                     "₹40,000 reserve intact", "except where you approve"):  # fmt: skip
        assert fragment in text
    empty = await MockAssistant().summarize_plan(
        facts(buy_now=[], scheduled=[], postponed=[], late=[], scenario_names=["As expected"])
    )
    assert "nothing to plan" in empty
    # With nothing scheduled, the summary must not talk about "every scheduled purchase".
    two = await MockAssistant().summarize_plan(
        facts(buy_now=[], scheduled=[], postponed=[], late=[],
              scenario_names=["As expected", "Salary delayed 1 month"])
    )  # fmt: skip
    assert "scheduled purchase" not in two
    assert "reserve stays intact in both scenarios checked (As expected and Salary delayed" in two


async def test_mock_summary_never_claims_safety_for_a_scenario_that_breaks_anyway() -> None:
    text = await MockAssistant().summarize_plan(
        facts(unsafe_anyway=["Salary delayed 2 months"], buy_now=[], scheduled=[], late=[])
    )
    assert "Warning: in Salary delayed 2 months" in text
    assert "intact in the scenario checked (As expected)." in text
    assert "Salary delayed 2 months)" not in text
    only_unsafe = await MockAssistant().summarize_plan(
        facts(scenario_names=["Salary delayed 2 months"], unsafe_anyway=["Salary delayed 2 months"])
    )
    assert "intact" not in only_unsafe


def test_format_amount() -> None:
    assert format_amount(14999900, "INR") == "₹1,49,999"
    assert format_amount(123456789, "INR") == "₹12,34,567.89"
    assert format_amount(150, "USD") == "$1.50"
    assert format_amount(1234567, "JPY") == "¥1,234,567"
    assert format_amount(-50000, "AED") == "-AED 500"


# ---------- Claude provider with a fake client ----------
class FakeMessages:
    def __init__(self, outcome: Any) -> None:
        self.outcome = outcome
        self.calls: list[dict[str, Any]] = []

    async def create(self, **kwargs: Any) -> Any:
        self.calls.append(kwargs)
        if isinstance(self.outcome, Exception):
            raise self.outcome
        return self.outcome


def fake_client(outcome: Any) -> tuple[Any, FakeMessages]:
    msgs = FakeMessages(outcome)
    return SimpleNamespace(beta=SimpleNamespace(messages=msgs)), msgs


def reply(payload: Any, stop: str = "end_turn") -> Any:
    text = payload if isinstance(payload, str) else json.dumps(payload)
    return SimpleNamespace(stop_reason=stop, content=[SimpleNamespace(type="text", text=text)])


GOOD_ITEM = {
    "name": "Salon visit", "tier": "want", "kind": "service", "priority": 3, "amount": "1500",
    "currency": "INR", "quantity": None, "target_date": "2026-11-23", "deadline_type": "soft",
    "location": None,
}  # fmt: skip


async def test_claude_parse_uses_structured_output_and_validates() -> None:
    client, msgs = fake_client(reply(GOOD_ITEM))
    draft = await AnthropicAssistant("k", client=client).parse_item("salon", CTX)
    assert draft.target_date == date(2026, 11, 23) and draft.amount == "1500"
    call = msgs.calls[0]
    assert call["model"] == "claude-opus-5-5"
    assert call["output_config"]["format"]["type"] == "json_schema"
    assert call["fallbacks"] == "default" and call["betas"] == ["server-side-fallback-2026-07-01"]
    assert '"note": "salon"' in call["messages"][0]["content"]


def _status_error(cls: type[anthropic.APIStatusError], code: int) -> anthropic.APIStatusError:
    request = httpx.Request("POST", "https://api.anthropic.com/v1/messages")
    return cls("err", response=httpx.Response(code, request=request), body=None)


@pytest.mark.parametrize(
    ("outcome", "reason"),
    [
        (reply(GOOD_ITEM, stop="refusal"), "declined"),
        (reply(GOOD_ITEM, stop="max_tokens"), "cut off"),
        (reply("not json"), "malformed"),
        (reply([1, 2]), "malformed"),
        (reply({**GOOD_ITEM, "amount": "1,500.00"}), "validation"),
        (reply({**GOOD_ITEM, "tier": "luxury"}), "validation"),
        (SimpleNamespace(stop_reason="end_turn", content=[]), "no answer"),
        (_status_error(anthropic.AuthenticationError, 401), "rejected"),
        (_status_error(anthropic.PermissionDeniedError, 403), "cannot access"),
        (_status_error(anthropic.RateLimitError, 429), "rate limited"),
        (_status_error(anthropic.InternalServerError, 500), "returned an error"),
        (anthropic.APIConnectionError(request=httpx.Request("POST", "https://x")), "reach"),
    ],
)
async def test_claude_failures_become_unavailable(outcome: Any, reason: str) -> None:
    client, _ = fake_client(outcome)
    with pytest.raises(AssistantUnavailableError, match=reason):
        await AnthropicAssistant("k", client=client).parse_item("salon", CTX)


async def test_claude_summary_rejects_invented_numbers() -> None:
    ok, _ = fake_client(
        reply({"summary": "Buy Headphones now; Laptop on 2 Jan 2027. ₹40,000 stays safe."})
    )
    assert "Headphones" in await AnthropicAssistant("k", client=ok).summarize_plan(facts())
    bad, _ = fake_client(reply({"summary": "You will save ₹12,345 by waiting."}))
    with pytest.raises(AssistantUnavailableError, match="unverified numbers"):
        await AnthropicAssistant("k", client=bad).summarize_plan(facts())
    empty, _ = fake_client(reply({"summary": "  "}))
    with pytest.raises(AssistantUnavailableError, match="empty"):
        await AnthropicAssistant("k", client=empty).summarize_plan(facts())


def _user(mode: LlmMode, key: str | None) -> User:
    return User(
        email="a@b.c", password_hash="x", display_name="A", country="IN", base_currency="INR",
        llm_mode=mode, llm_api_key_encrypted=key,
    )  # fmt: skip


async def test_service_uses_mock_by_default_and_falls_back(monkeypatch: pytest.MonkeyPatch) -> None:
    r = await service.parse_item(_user(LlmMode.MOCK, None), "salon 1500", CTX)
    assert r.source == "mock" and r.notice is None

    broken = _user(LlmMode.ANTHROPIC, "not-a-valid-token")
    r = await service.parse_item(broken, "salon 1500", CTX)
    assert r.source == "mock" and r.notice and "could not be read" in r.notice

    async def refuse(self: AnthropicAssistant, *_a: Any) -> Any:
        raise AssistantUnavailableError("Claude declined this request.")

    monkeypatch.setattr(AnthropicAssistant, "parse_item", refuse)
    monkeypatch.setattr(AnthropicAssistant, "summarize_plan", refuse)
    claude_user = _user(LlmMode.ANTHROPIC, encrypt_secret("sk-ant-test"))
    r = await service.parse_item(claude_user, "salon 1500", CTX)
    assert r.source == "mock" and r.notice and r.notice.startswith("Claude declined")
    s = await service.summarize_plan(claude_user, facts())
    assert s.source == "mock" and "built-in summary" in (s.notice or "")

    async def good(self: AnthropicAssistant, *_a: Any) -> Any:
        return "Claude summary"

    monkeypatch.setattr(AnthropicAssistant, "summarize_plan", good)
    s = await service.summarize_plan(claude_user, facts())
    assert (s.value, s.source, s.notice) == ("Claude summary", "anthropic", None)


# ---------- Alternatives search (web search server tool) ----------
def search_reply(urls: list[str], text: str, stop: str = "end_turn") -> Any:
    results = [SimpleNamespace(type="web_search_result", url=u, title="t") for u in urls]
    return SimpleNamespace(
        stop_reason=stop,
        content=[
            SimpleNamespace(type="server_tool_use", name="web_search"),
            SimpleNamespace(type="web_search_tool_result", content=results),
            SimpleNamespace(type="text", text=text),
        ],
    )


class Sequenced(FakeMessages):
    def __init__(self, outcomes: list[Any]) -> None:
        super().__init__(None)
        self.outcomes = outcomes

    async def create(self, **kwargs: Any) -> Any:
        self.calls.append(kwargs)
        return self.outcomes.pop(0)


async def test_alternatives_keep_only_urls_returned_by_the_search() -> None:
    text = json.dumps([
        {"name": "Pixel 11", "url": "https://shop.example/pixel-11/", "why": "Newer chip",
         "price_text": "₹74,999"},
        {"name": "Made-up X", "url": "https://invented.example/x", "why": "Hallucinated"},
        {"name": "Bad", "url": "ftp://nope", "why": "Wrong scheme"},
        "not an object",
    ])  # fmt: skip
    msgs = Sequenced([search_reply(["https://www.shop.example/pixel-11"], "Here:\n" + text)])
    client = SimpleNamespace(beta=SimpleNamespace(messages=msgs))
    found, dropped = await AnthropicAssistant("k", client=client).find_alternatives(
        name="Pixel 10", kind="product", country="IN", budget="₹80,000"
    )
    assert [f.name for f in found] == ["Pixel 11"] and dropped == 1
    tool = msgs.calls[0]["tools"][0]
    assert tool["type"] == "web_search_20260209" and tool["max_uses"] == 5
    assert "format" not in msgs.calls[0]["output_config"]  # citations + structured output clash


async def test_alternatives_resume_after_pause_turn_and_handle_failures() -> None:
    paused = search_reply(["https://a.example/one"], "", stop="pause_turn")
    final = search_reply(["https://b.example/two"], json.dumps([
        {"name": "One", "url": "https://a.example/one", "why": "w"},
        {"name": "Two", "url": "https://b.example/two", "why": "w"},
    ]))  # fmt: skip
    msgs = Sequenced([paused, final])
    found, _ = await AnthropicAssistant("k", client=SimpleNamespace(
        beta=SimpleNamespace(messages=msgs))).find_alternatives(
        name="x", kind="product", country="IN", budget="1")  # fmt: skip
    assert {f.name for f in found} == {"One", "Two"}  # URLs from both turns count
    second = msgs.calls[1]["messages"]
    assert [m["role"] for m in second] == ["user", "assistant"]  # resumed, no extra prompt

    endless = Sequenced([search_reply([], "", stop="pause_turn")] * 4)
    with pytest.raises(AssistantUnavailableError, match="too long"):
        await AnthropicAssistant("k", client=SimpleNamespace(
            beta=SimpleNamespace(messages=endless))).find_alternatives(
            name="x", kind="product", country="IN", budget="1")  # fmt: skip

    refused = Sequenced([search_reply([], "", stop="refusal")])
    with pytest.raises(AssistantUnavailableError, match="declined"):
        await AnthropicAssistant("k", client=SimpleNamespace(
            beta=SimpleNamespace(messages=refused))).find_alternatives(
            name="x", kind="product", country="IN", budget="1")  # fmt: skip

    garbage = Sequenced([search_reply(["https://a.example/one"], "no json here")])
    found, dropped = await AnthropicAssistant("k", client=SimpleNamespace(
        beta=SimpleNamespace(messages=garbage))).find_alternatives(
        name="x", kind="product", country="IN", budget="1")  # fmt: skip
    assert found == [] and dropped == 0


async def test_alternatives_service_messages(monkeypatch: pytest.MonkeyPatch) -> None:
    mock_user = _user(LlmMode.MOCK, None)
    found, _, msg = await service.find_alternatives(
        mock_user, name="x", kind="product", country="IN", budget="1"
    )
    assert found == [] and "Claude API key" in msg

    claude_user = _user(LlmMode.ANTHROPIC, encrypt_secret("sk-ant-test"))

    async def none(self: AnthropicAssistant, **_k: Any) -> Any:
        return [], 2

    monkeypatch.setattr(AnthropicAssistant, "find_alternatives", none)
    _, dropped, msg = await service.find_alternatives(
        claude_user, name="x", kind="product", country="IN", budget="1"
    )
    assert dropped == 2 and "could be verified" in msg

    async def fail(self: AnthropicAssistant, **_k: Any) -> Any:
        raise AssistantUnavailableError("Claude is rate limited right now.")

    monkeypatch.setattr(AnthropicAssistant, "find_alternatives", fail)
    _, _, msg = await service.find_alternatives(
        claude_user, name="x", kind="product", country="IN", budget="1"
    )
    assert msg == "Claude is rate limited right now."


async def test_mock_summary_points_out_a_missing_reserve() -> None:
    text = await MockAssistant().summarize_plan(facts(reserve="₹0", reserve_zero=True))
    assert "no emergency reserve set up" in text and "intact" not in text
