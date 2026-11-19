# booker-agent

Минимальный AI-агент на LangChain, который работает как обёртка над API
[restful-booker](https://restful-booker.herokuapp.com/) на естественном языке:
принимает запрос, интерпретирует намерение через GigaChat, вызывает нужные
методы API через инструменты и возвращает структурированный результат со
статусом выполнения.

## Возможности

- Список всех бронирований и фильтрация по имени, фамилии и датам.
- Получение бронирования по ID.
- Создание, полное обновление через `PUT` и частичное через `PATCH`.
- Удаление бронирования.
- Health-check API.
- Автоматическая авторизация для `PATCH`, `PUT` и `DELETE`: токен кэшируется
  и обновляется при `401/403`.
- Единый JSON-контракт результата: `status`, `operation`, `http_status`,
  `data`, `summary`, `tool_calls`, `error`.
- CLI с one-shot запросом и интерактивным REPL, подтверждение опасных операций.

## Требования

- Python 3.10+ (ограничение `langchain-gigachat`).
- Authorization key GigaChat (`GIGACHAT_CREDENTIALS`).

## Установка

```bash
python3.12 -m venv .venv
source .venv/bin/activate
pip install -e ".[dev]"
```

Через `uv`:

```bash
uv venv --python 3.12
uv pip install -e ".[dev]"
```

Скопируйте переменные окружения и укажите ключ GigaChat:

```bash
cp .env.example .env
# отредактируйте GIGACHAT_CREDENTIALS
```

Основные переменные:

| Переменная | Назначение | По умолчанию |
|---|---|---|
| `GIGACHAT_CREDENTIALS` | Authorization key GigaChat | обязательна |
| `GIGACHAT_SCOPE` | Scope API | `GIGACHAT_API_PERS` |
| `GIGACHAT_MODEL` | Модель | `GigaChat-2` |
| `BOOKER_BASE_URL` | Базовый URL API | `https://restful-booker.herokuapp.com` |
| `BOOKER_USERNAME` / `BOOKER_PASSWORD` | Учётные данные API | `admin` / `password123` |
| `BOOKER_TIMEOUT` | Таймаут запроса, секунды | `15` |
| `BOOKER_MAX_RETRIES` | Повторы при `429`, `502`, `503`, `504` | `2` |
| `AGENT_MAX_STEPS` | Лимит шагов tool calling | `6` |
| `AGENT_TEMPERATURE` | Температура модели | `0.0` |
| `AGENT_LLM_TIMEOUT` | Таймаут вызова LLM, секунды | `60` |
| `AGENT_VERBOSE` | Подробный вывод по умолчанию | `false` |

## Использование

```bash
# one-shot
booker "покажи все бронирования"

# только JSON в stdout
booker --json "найди бронирования Sally Brown"

# трассировка вызовов инструментов в stderr
booker --verbose "покажи бронирование 1"

# опасная операция без подтверждения
booker --yes "удали бронирование 1"

# интерактивный режим
booker
```

Пример запроса на создание:

```bash
booker --yes "создай бронирование для Maria Ivanova с 2026-12-01 по 2026-12-05, \
стоимость 150, предоплата внесена, нужен завтрак"
```

Команды REPL: `/help`, `/reset`, `/history`, `/exit`.

Коды возврата: `0` — `status=success`, `1` — ошибка операции,
`2` — ошибка конфигурации.

### Запуск без console script

Если команда `booker` недоступна (пакет не установлен или виртуальное окружение
не активировано), запускайте через Python-файл из корня проекта:

```bash
# launcher из корня проекта, сам добавляет src в sys.path
python main.py "покажи все бронирования"
python main.py --json "покажи бронирование 1"
python main.py --verbose --yes "удали бронирование 1"

# либо как модуль
PYTHONPATH=src python -m booker_agent.cli "покажи все бронирования"
```

Важно: зависимости (`langchain-gigachat`, `langchain-core`, `httpx`, `pydantic`,
`pydantic-settings`, `rich`) всё равно должны быть установлены в активное
окружение Python 3.10+. Команда `pip install -e ".[dev]"` ставит и их, и
создаёт console script `booker`.

## Формат результата

### Формат ответа инструментов

Все семь инструментов возвращают текст строго из четырёх строк:

```text
Status: success | error
Action: <описание действия>
Data: <результат API в JSON>
Errors: <если есть, иначе none>
```

Успешный вызов:

```text
Status: success
Action: get_booking: Бронирование 1 получено (HTTP 200)
Data: {"firstname":"Sally","lastname":"Brown","totalprice":111}
Errors: none
```

Ошибка:

```text
Status: error
Action: get_booking: Бронирование с указанным ID не найдено (HTTP 404)
Data: null
Errors: not_found: Бронирование с указанным ID не найдено
```

`Action` содержит имя операции, краткое описание и HTTP-код. В начале `Errors`
идёт детальный код (`not_found`, `unauthorized`, `invalid_request`,
`server_error`, `network_error`, `config_error`), поэтому агент восстанавливает
точный статус для `AgentResult`, а модель видит понятное описание проблемы.
Сериализация и разбор формата находятся в [`response.py`](src/booker_agent/response.py).

### Итоговый результат агента

```json
{
  "status": "success",
  "operation": "get_booking",
  "http_status": 200,
  "data": {
    "firstname": "Sally",
    "lastname": "Brown",
    "totalprice": 111,
    "depositpaid": true,
    "bookingdates": {"checkin": "2026-12-01", "checkout": "2026-12-05"},
    "additionalneeds": "Breakfast"
  },
  "summary": "Бронирование 1 принадлежит Sally Brown.",
  "tool_calls": [
    {"tool": "get_booking", "args": {"booking_id": 1}, "status": "success", "http_status": 200}
  ],
  "error": null
}
```

Статусы: `success`, `not_found`, `unauthorized`, `invalid_request`,
`server_error`, `network_error`, `needs_clarification`, `max_steps_reached`,
`config_error`.

`status`, `http_status` и `data` берутся из фактического HTTP-ответа, а не из
текста модели: LLM отвечает только за выбор инструмента и краткое резюме.

## Архитектура

```
CLI (one-shot / REPL)
  └── AgentRunner (цикл tool calling, лимит шагов)
        ├── GigaChat bind_tools(tool_choice="auto")
        ├── tools: list, get, create, update, patch, delete, ping
        └── BookerClient (httpx, токен, retry, маппинг ошибок)
              └── restful-booker API
```

Инструменты отвечают модели текстом в формате `Status / Action / Data / Errors`.
Исключения не выходят наружу: `404` превращается в `not_found`, `401/403` — в
`unauthorized`, `400/422` — в `invalid_request`, `5xx` — в `server_error`,
таймаут — в `network_error`. Код статуса сохраняется в строке `Errors`, а агент
разбирает ответ обратно в `ToolResult`. Ошибки валидации аргументов модель видит
и может исправить вызов на следующем шаге.

GigaChat не поддерживает параллельные tool calls и `tool_choice="any"`, поэтому
цикл обрабатывает вызовы последовательно, а `tool_choice` всегда `auto`.

## Структура проекта

```
src/booker_agent/
├── config.py    # настройки из окружения и .env
├── models.py    # Booking, BookingUpdate, ToolResult, AgentResult
├── errors.py    # исключения и статусы
├── client.py    # HTTP-клиент: авторизация, кэш токена, retry
├── tools.py     # 7 LangChain-инструментов
├── response.py  # формат ответа инструментов и разбор обратно в ToolResult
├── prompts.py   # системный промпт
├── agent.py     # цикл tool calling и сборка результата
└── cli.py       # argparse, REPL, вывод
tests/
├── test_client.py  # respx: контракты, авторизация, retry
├── test_tools.py   # JSON-контракт и валидация инструментов
├── test_agent.py   # фейковая LLM: цикл, лимит шагов, ошибки
└── test_live.py    # live-проверки против реального API
```

## Тесты

```bash
pytest                 # без сети, на respx и фейковой LLM
pytest -m live         # live-проверки, только с RUN_LIVE=1
RUN_LIVE=1 pytest -m live
ruff check .
```

Live-тесты создают собственное бронирование и удаляют его в `finally`.

## Ограничения

- Токен restful-booker живёт около 10 минут; клиент кэширует его на 9 минут.
- Heroku-приложение может «просыпаться»: первый запрос бывает медленным,
  для этого есть retry и `ping_api`.
- `PATCH` с изменением дат требует обе даты: API заменяет объект
  `bookingdates` целиком.
- Очистить `additionalneeds` можно пустой строкой; `null` означает
  «поле не передано».
- Модель GigaChat может неуверенно выбирать инструмент при неоднозначном
  запросе; `temperature=0`, подробные описания инструментов и `--verbose`
  упрощают диагностику.
- История REPL хранится только в памяти процесса.

## Безопасность

- Секреты читаются только из окружения или `.env`; `.env` в `.gitignore`.
- Токены не попадают в `AgentResult`, логи и сообщения об ошибках.
- `create`, `update`, `patch`, `delete` требуют подтверждения в интерактивном
  режиме; в неинтерактивном запуске нужен явный флаг `--yes`.
