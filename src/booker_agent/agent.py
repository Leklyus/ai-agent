"""Цикл tool calling и сборка структурированного результата."""

from __future__ import annotations

import logging
from collections.abc import Sequence
from typing import Any

from langchain_core.language_models.chat_models import BaseChatModel
from langchain_core.messages import AIMessage, BaseMessage, HumanMessage, SystemMessage, ToolMessage
from pydantic import ValidationError as PydanticValidationError

from .client import BookerClient
from .config import Settings
from .models import AgentResult, ToolCallTrace, ToolResult
from .prompts import build_system_prompt
from .response import format_tool_result, parse_tool_result
from .tools import ConfirmCallback, build_tools, format_validation_error

logger = logging.getLogger(__name__)


def _content_to_text(content: Any) -> str:
    if isinstance(content, str):
        return content.strip()
    if isinstance(content, list):
        parts: list[str] = []
        for block in content:
            if isinstance(block, str):
                parts.append(block)
            elif isinstance(block, dict) and block.get("type") == "text":
                parts.append(str(block.get("text", "")))
        return "\n".join(part for part in parts if part).strip()
    return str(content).strip() if content is not None else ""


class AgentRunner:
    """Минимальный агент: LLM выбирает инструмент, результат собирается детерминированно."""

    def __init__(
        self,
        settings: Settings,
        *,
        client: BookerClient | None = None,
        llm: BaseChatModel | None = None,
        confirm: ConfirmCallback | None = None,
    ) -> None:
        self._settings = settings
        self._client = client or BookerClient(settings)
        self._tools = build_tools(self._client, confirm=confirm)
        self._tools_by_name = {tool.name: tool for tool in self._tools}
        self._llm = llm or self._build_llm(settings)
        self._llm_with_tools = self._llm.bind_tools(self._tools, tool_choice="auto")

    @staticmethod
    def _build_llm(settings: Settings) -> BaseChatModel:
        # Импорт внутри метода: тесты и --help не требуют рабочего клиента GigaChat.
        from langchain_gigachat import GigaChat

        return GigaChat(
            model=settings.gigachat_model,
            credentials=settings.require_gigachat_credentials(),
            scope=settings.gigachat_scope,
            verify_ssl_certs=settings.gigachat_verify_ssl_certs,
            temperature=settings.agent_temperature,
            timeout=settings.agent_llm_timeout,
        )

    @property
    def tools(self) -> list[Any]:
        return list(self._tools)

    def run(self, user_input: str, history: Sequence[BaseMessage] | None = None) -> AgentResult:
        messages: list[BaseMessage] = [SystemMessage(content=build_system_prompt())]
        if history:
            messages.extend(history)
        messages.append(HumanMessage(content=user_input))

        trace: list[ToolCallTrace] = []
        last: ToolResult | None = None

        for step in range(1, self._settings.agent_max_steps + 1):
            try:
                ai_message = self._llm_with_tools.invoke(messages)
            except Exception as exc:  # ошибки провайдера LLM
                logger.exception("Ошибка вызова LLM")
                return AgentResult(
                    status="server_error",
                    operation=last.operation if last else None,
                    http_status=last.http_status if last else None,
                    data=last.data if last else None,
                    summary="",
                    tool_calls=trace,
                    error=f"Ошибка LLM: {exc}",
                )

            if not isinstance(ai_message, AIMessage):
                ai_message = AIMessage(content=_content_to_text(getattr(ai_message, "content", ai_message)))

            messages.append(ai_message)
            tool_calls = list(ai_message.tool_calls or [])

            if not tool_calls:
                summary = _content_to_text(ai_message.content)
                if last is None:
                    return AgentResult(
                        status="needs_clarification",
                        summary=summary
                        or "Не удалось определить действие. Уточните, что нужно сделать с бронированиями.",
                        tool_calls=trace,
                    )
                return AgentResult(
                    status=last.status,
                    operation=last.operation,
                    http_status=last.http_status,
                    data=last.data,
                    summary=summary or last.message,
                    tool_calls=trace,
                    error=last.error,
                )

            for call in tool_calls:
                payload, raw = self._execute(call)
                trace.append(
                    ToolCallTrace(
                        tool=call.get("name") or "unknown",
                        args=dict(call.get("args") or {}),
                        status=payload.status,
                        http_status=payload.http_status,
                        error=payload.error,
                    )
                )
                last = payload
                messages.append(
                    ToolMessage(
                        content=raw,
                        tool_call_id=call.get("id") or f"call_{step}_{len(trace)}",
                        name=call.get("name"),
                    )
                )

        logger.warning("Достигнут лимит шагов агента: %s", self._settings.agent_max_steps)
        return AgentResult(
            status="max_steps_reached",
            operation=last.operation if last else None,
            http_status=last.http_status if last else None,
            data=last.data if last else None,
            summary="Достигнут лимит шагов, агент не успел сформировать итог.",
            tool_calls=trace,
            error=f"Лимит шагов: {self._settings.agent_max_steps}",
        )

    def _execute(self, call: dict[str, Any]) -> tuple[ToolResult, str]:
        """Выполнить tool call и вернуть payload плюс текст ответа для ToolMessage."""
        name = call.get("name") or ""
        args = dict(call.get("args") or {})
        tool_instance = self._tools_by_name.get(name)

        if tool_instance is None:
            payload = ToolResult(
                status="invalid_request",
                operation=name or "unknown",
                error=f"Неизвестный инструмент: {name}",
                message="Такого инструмента нет. Используй только доступные инструменты.",
            )
            return payload, format_tool_result(payload)

        try:
            raw = tool_instance.invoke(args)
        except PydanticValidationError as exc:
            payload = ToolResult(
                status="invalid_request",
                operation=name,
                error=format_validation_error(exc),
                message="Аргументы не прошли валидацию. Исправь их и повтори вызов.",
            )
            return payload, format_tool_result(payload)
        except Exception as exc:  # pragma: no cover - защита от сбоя инструмента
            logger.exception("Инструмент %s завершился ошибкой", name)
            payload = ToolResult(
                status="server_error",
                operation=name,
                error=f"Ошибка инструмента: {exc}",
                message="Внутренняя ошибка инструмента.",
            )
            return payload, format_tool_result(payload)

        if not isinstance(raw, str):
            raw = str(raw)

        return parse_tool_result(raw, operation=name), raw

    def close(self) -> None:
        self._client.close()

    def __enter__(self) -> AgentRunner:
        return self

    def __exit__(self, *exc_info: object) -> None:
        self.close()
