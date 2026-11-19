"""CLI: one-shot запрос и интерактивный REPL."""

from __future__ import annotations

import argparse
import json
import logging
import sys
from collections.abc import Sequence
from typing import Any

from langchain_core.messages import AIMessage, BaseMessage, HumanMessage
from pydantic import ValidationError
from rich.console import Console
from rich.pretty import Pretty

from . import __version__
from .agent import AgentRunner
from .config import get_settings
from .errors import ConfigError
from .models import AgentResult
from .tools import ConfirmCallback

console = Console()
error_console = Console(stderr=True)
MAX_HISTORY_MESSAGES = 10

STATUS_STYLES = {
    "success": "green",
    "needs_clarification": "yellow",
    "not_found": "yellow",
    "max_steps_reached": "yellow",
}


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="booker",
        description="AI-агент на естественном языке поверх restful-booker API.",
    )
    parser.add_argument(
        "query",
        nargs="*",
        help="Запрос на естественном языке. Без запроса запускается интерактивный режим.",
    )
    parser.add_argument("--json", action="store_true", help="Печатать результат в JSON.")
    parser.add_argument(
        "--verbose",
        action="store_true",
        help="Показывать вызовы инструментов и отладочные сообщения.",
    )
    parser.add_argument(
        "--yes",
        action="store_true",
        help="Не запрашивать подтверждение для create, update, patch и delete.",
    )
    parser.add_argument("--version", action="version", version=f"booker-agent {__version__}")
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)

    try:
        settings = get_settings()
    except ValidationError as exc:
        error_console.print(f"[red]Некорректные настройки:[/] {exc}")
        return 2

    verbose = args.verbose or settings.agent_verbose
    logging.basicConfig(
        level=logging.DEBUG if verbose else logging.WARNING,
        format="%(levelname)s %(name)s: %(message)s",
        stream=sys.stderr,
    )

    if not settings.has_gigachat_credentials:
        error_console.print(
            "[red]Не задан GIGACHAT_CREDENTIALS.[/] "
            "Скопируйте .env.example в .env и укажите ключ авторизации GigaChat."
        )
        return 2

    try:
        runner = AgentRunner(settings, confirm=_build_confirm(args.yes))
    except ConfigError as exc:
        error_console.print(f"[red]{exc.message}[/]")
        return 2

    with runner:
        query = " ".join(args.query).strip()
        if query:
            result = runner.run(query)
            render(result, as_json=args.json, verbose=verbose)
            return 0 if result.status == "success" else 1
        return _repl(runner, as_json=args.json, verbose=verbose)


def _build_confirm(auto_yes: bool) -> ConfirmCallback | None:
    if auto_yes:
        return None
    if sys.stdin.isatty():
        return _ask_confirmation
    return _deny_confirmation


def _ask_confirmation(operation: str, payload: dict[str, Any]) -> bool:
    console.print(
        f"\n[yellow]Подтверждение[/] {operation}: {json.dumps(payload, ensure_ascii=False)}"
    )
    try:
        answer = input("Выполнить? [y/N]: ").strip().lower()
    except EOFError:
        return False
    return answer in {"y", "yes", "д", "да"}


def _deny_confirmation(operation: str, payload: dict[str, Any]) -> bool:
    error_console.print(
        f"[yellow]Операция {operation} не выполнена:[/] для неинтерактивного запуска добавьте флаг --yes."
    )
    return False


def _repl(runner: AgentRunner, *, as_json: bool, verbose: bool) -> int:
    console.print("[bold]Интерактивный режим.[/] Команды: /help, /reset, /history, /exit")
    history: list[BaseMessage] = []

    while True:
        try:
            line = input("\nвы> ").strip()
        except (EOFError, KeyboardInterrupt):
            console.print()
            return 0

        if not line:
            continue

        if line.startswith("/"):
            command = line.lower()
            if command in {"/exit", "/quit", "/q"}:
                return 0
            if command == "/help":
                console.print(
                    "Опишите задачу обычным языком, например: «покажи все бронирования».\n"
                    "/reset — очистить историю, /history — показать историю, /exit — выйти."
                )
                continue
            if command == "/reset":
                history.clear()
                console.print("История очищена.")
                continue
            if command == "/history":
                if not history:
                    console.print("[dim]История пуста.[/]")
                else:
                    for message in history:
                        console.print(f"[dim]{message.type}:[/] {message.content}")
                continue
            console.print(f"Неизвестная команда: {line}. Доступны /help, /reset, /history, /exit.")
            continue

        result = runner.run(line, history)
        render(result, as_json=as_json, verbose=verbose)

        history.extend(
            [
                HumanMessage(content=line),
                AIMessage(content=result.summary or result.status),
            ]
        )
        del history[:-MAX_HISTORY_MESSAGES]


def render(result: AgentResult, *, as_json: bool, verbose: bool) -> None:
    if as_json:
        print(json.dumps(result.model_dump(mode="json"), ensure_ascii=False, indent=2))
        return

    if verbose:
        for item in result.tool_calls:
            arguments = json.dumps(item.args, ensure_ascii=False)
            http = f" HTTP {item.http_status}" if item.http_status else ""
            error_console.print(f"[dim]→ {item.tool}({arguments}) = {item.status}{http}[/]")

    style = STATUS_STYLES.get(result.status, "red")
    console.print(
        f"[{style}]{result.status}[/] · {result.operation or '-'} · HTTP {result.http_status or '-'}"
    )
    if result.summary:
        console.print(result.summary)
    if result.data is not None:
        _print_data(result.data)
    if result.error:
        console.print(f"[red]error:[/] {result.error}")


def _print_data(data: Any) -> None:
    if isinstance(data, list):
        if not data:
            console.print("[dim]пусто[/]")
            return
        if all(isinstance(item, dict) and "bookingid" in item for item in data):
            ids = ", ".join(str(item["bookingid"]) for item in data)
            console.print(f"[bold]ID:[/] {ids}")
            return
    if isinstance(data, (dict, list)):
        console.print(Pretty(data))
        return
    console.print(str(data))


if __name__ == "__main__":
    raise SystemExit(main())
