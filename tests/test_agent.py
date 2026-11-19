"""Тесты цикла агента на фейковой LLM: без сети и без GigaChat."""

from __future__ import annotations

import httpx
import respx
from langchain_core.language_models.chat_models import BaseChatModel
from langchain_core.messages import AIMessage, BaseMessage
from langchain_core.outputs import ChatGeneration, ChatResult

from booker_agent.agent import AgentRunner
from booker_agent.client import BookerClient
from booker_agent.config import Settings

BASE_URL = "https://restful-booker.herokuapp.com"


class FakeToolCallingModel(BaseChatModel):
    """Модель, которая отдаёт заранее заданные ответы и игнорирует bind_tools."""

    responses: list[AIMessage]
    index: int = 0

    @property
    def _llm_type(self) -> str:
        return "fake-tool-calling"

    def bind_tools(self, tools, **kwargs):  # type: ignore[override]
        return self

    def _generate(
        self,
        messages: list[BaseMessage],
        stop: list[str] | None = None,
        run_manager=None,
        **kwargs,
    ) -> ChatResult:
        message = self.responses[min(self.index, len(self.responses) - 1)]
        self.index += 1
        return ChatResult(generations=[ChatGeneration(message=message)])


def build_agent(
    settings: Settings,
    client: BookerClient,
    responses: list[AIMessage],
) -> AgentRunner:
    return AgentRunner(settings, client=client, llm=FakeToolCallingModel(responses=responses))


def tool_call(name: str, arguments: dict, call_id: str = "call_1") -> AIMessage:
    return AIMessage(
        content="",
        tool_calls=[{"name": name, "args": arguments, "id": call_id, "type": "tool_call"}],
    )


@respx.mock
def test_agent_returns_structured_success(
    settings: Settings,
    client: BookerClient,
    booking_payload: dict,
) -> None:
    respx.get(f"{BASE_URL}/booking/1").mock(
        return_value=httpx.Response(200, json=booking_payload)
    )
    agent = build_agent(
        settings,
        client,
        [
            tool_call("get_booking", {"booking_id": 1}),
            AIMessage(content="Бронирование 1 принадлежит Sally Brown."),
        ],
    )

    result = agent.run("покажи бронирование 1")

    assert result.status == "success"
    assert result.operation == "get_booking"
    assert result.http_status == 200
    assert result.data["firstname"] == "Sally"
    assert result.summary == "Бронирование 1 принадлежит Sally Brown."
    assert len(result.tool_calls) == 1
    assert result.tool_calls[0].status == "success"
    assert result.error is None


@respx.mock
def test_agent_reports_not_found(settings: Settings, client: BookerClient) -> None:
    respx.get(f"{BASE_URL}/booking/999").mock(return_value=httpx.Response(404, text="Not Found"))
    agent = build_agent(
        settings,
        client,
        [
            tool_call("get_booking", {"booking_id": 999}),
            AIMessage(content="Бронирования с таким ID нет."),
        ],
    )

    result = agent.run("покажи бронирование 999")

    assert result.status == "not_found"
    assert result.http_status == 404
    assert result.error


def test_agent_asks_for_clarification(settings: Settings, client: BookerClient) -> None:
    agent = build_agent(settings, client, [AIMessage(content="Уточните даты заезда и выезда.")])

    result = agent.run("создай бронирование")

    assert result.status == "needs_clarification"
    assert result.data is None
    assert result.tool_calls == []
    assert "Уточните" in result.summary


@respx.mock
def test_agent_stops_after_max_steps(settings: Settings, client: BookerClient) -> None:
    respx.get(f"{BASE_URL}/ping").mock(return_value=httpx.Response(201, text="Created"))
    limited = settings.model_copy(update={"agent_max_steps": 2})
    agent = build_agent(limited, client, [tool_call("ping_api", {})])

    result = agent.run("проверь API")

    assert result.status == "max_steps_reached"
    assert len(result.tool_calls) == 2
    assert result.error


def test_agent_handles_unknown_tool(settings: Settings, client: BookerClient) -> None:
    agent = build_agent(
        settings,
        client,
        [
            tool_call("drop_database", {}),
            AIMessage(content="Такого действия нет."),
        ],
    )

    result = agent.run("удали всё")

    assert result.tool_calls[0].tool == "drop_database"
    assert result.tool_calls[0].status == "invalid_request"
    assert result.status == "invalid_request"


def test_agent_handles_invalid_arguments(settings: Settings, client: BookerClient) -> None:
    agent = build_agent(
        settings,
        client,
        [
            tool_call("get_booking", {"booking_id": "abc"}),
            AIMessage(content="Нужен числовой ID."),
        ],
    )

    result = agent.run("покажи бронирование")

    assert result.tool_calls[0].status == "invalid_request"
    assert result.status == "invalid_request"
