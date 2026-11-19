# Стек проекта
Агент: SourceCraft Code \
ЯП: Python \
API: https://restful-booker.herokuapp.com/ \
IDE: VS Code \
LLM: GigaChat
# Промпты
# Prompt 1. 
Напиши план создания следующего проекта на Python.
Должен получиться минимальный AI-агент на LangChain, который работает как обёртка над API на естественном языке: принимает запрос на естественном языке, интерпретирует намерение, вызывает нужные API-методы через tool и возвращает структурированный результат со статусом выполнения.
API: https://restful-booker.herokuapp.com/ 
### 1. Список всех ID бронирований
curl https://restful-booker.herokuapp.com/booking

### 2. Одно бронирование по ID (заголовок Accept обязателен)
curl https://restful-booker.herokuapp.com/booking/1 \
  -H "Accept: application/json"

### 3. Фильтр по имени и фамилии гостя
curl "https://restful-booker.herokuapp.com/booking?firstname=Sally&lastname=Brown"

### 4. Создать бронирование
curl -X POST https://restful-booker.herokuapp.com/booking \
  -H "Content-Type: application/json" \
  -H "Accept: application/json" \
  -d '{"firstname":"Maria","lastname":"Ivanova","totalprice":150,
       "depositpaid":true,
       "bookingdates":{"checkin":"2026-12-01","checkout":"2026-12-05"},
       "additionalneeds":"Breakfast"}'

### 5. Частичное обновление (PATCH)
curl -X PATCH https://restful-booker.herokuapp.com/booking/1 \
  -H "Content-Type: application/json" \
  -H "Accept: application/json" \
  -H "Cookie: token=ВАШ_ТОКЕН" \
  -d '{"totalprice":250}'

### 6. Удаление
curl -X DELETE https://restful-booker.herokuapp.com/booking/1 \
  -H "Cookie: token=ВАШ_ТОКЕН"
# Result 1
***Уточнение модели LLM***\
LLM выбран
  GigaChat API (langchain-gigachat) как LLM + CLI-интерфейс (REPL и one-shot) \
  Создан файл: /plans/booking-agent-plan.md


# Prompt 2.
Создай структуру проекта согласно плану.
# Result 2
Создана структура проекта согласно плану:
```
pyproject.toml          # зависимости, console script booker, настройки pytest и ruff
.env.example            # шаблон переменных окружения
.gitignore
README.md
REPORT.md
plans/booking-agent-plan.md
src/booker_agent/
├── __init__.py
├── config.py           # Settings и get_settings на pydantic-settings
├── models.py           # Booking, BookingUpdate, ToolResult, AgentResult, статусы
├── errors.py           # BookerError и наследники со статусами
├── client.py           # BookerClient: 7 операций, токен, retry, маппинг ошибок
├── tools.py            # 7 LangChain-инструментов с args_schema
├── prompts.py          # системный промпт
├── agent.py            # AgentRunner: цикл tool calling
└── cli.py              # one-shot, REPL, --json, --verbose, --yes
tests/
├── conftest.py
├── test_client.py      # respx: контракты, авторизация, retry, таймауты
├── test_tools.py       # JSON-контракт инструментов и валидация
├── test_agent.py       # фейковая LLM: цикл, лимит шагов, ошибки
└── test_live.py        # live CRUD-цикл с маркером live
```

# Prompt 3
Реализуй содержимое модулей
# Result 3
Реализовано содержимое модулей:
- `client.py`: `Accept: application/json` для всех запросов, `POST /auth` с кэшем токена на 9 минут,
  повтор при `401/403` с обновлением токена, retry на `429/502/503/504` и таймауты, разбор
  `DELETE 201 Created` без парсинга JSON, маппинг `404 → not_found`, `401/403 → unauthorized`,
  `400/422 → invalid_request`, `5xx → server_error`.
- `tools.py`: инструменты `list_bookings`, `get_booking`, `create_booking`, `update_booking`,
  `patch_booking`, `delete_booking`, `ping_api`; каждый возвращает JSON-контракт `ToolResult`
  и не выбрасывает исключения наружу; для `PATCH` с датами требуются обе даты.
- `agent.py`: последовательный цикл tool calling с лимитом `AGENT_MAX_STEPS`, обработка неизвестных
  инструментов и невалидных аргументов, сборка `AgentResult` из фактического HTTP-ответа.
- `cli.py`: one-shot и REPL, команды `/help`, `/reset`, `/history`, `/exit`, подтверждение
  `create/update/patch/delete`, коды возврата `0/1/2`.

# Prompt 4
Зафиксируй формат ответа для всех tools:
Status: success | error
Action: <описание действия>
Data: <результат API>
Errors: <если есть>
# Result 4
Формат зафиксирован для всех семи инструментов в `response.py`:
```text
Status: success
Action: list_bookings: Найдено бронирований: 1 (HTTP 200)
Data: [{"bookingid":1}]
Errors: none
```

# Запуск проекта
Для запуска необходимо указать ключ GigaChat:
```bash
cp .env.example .env   # заполнить GIGACHAT_CREDENTIALS ё
python main.py "покажи все бронирования"
```

# Примеры запуска
## Запрос 1
python main.py "найди все бронирования клиента Josh Allen"
success · list_bookings · HTTP 200
## Ответ 1
Нашлось 190 бронирований на имя Josh Allen. Если нужно посмотреть конкретное бронирование или получить дополнительную информацию по какому-либо из них, укажите номер бронирования.
ID: 15, 16, 21, 25, 27, 28, 36, 40, 42, 44, 49, 53, 56, 61, 64, 68, 70, 72, 78, 79, 85, 86, 91, 95, 101, 102, 107, 108, 114, 118, 120, 124, 128, 132, 134, 138, 143, 146, 148, 154, 157, 159, 
163, 166, 170, 174, 177, 180, 184, 188, 192, 195, 196, 199, 207, 209, 210, 211, 219, 220, 227, 228, 233, 237, 240, 244, 249, 250, 255, 256, 261, 265, 268, 272

# Запрос 2
python main.py "что за бронь 102"
# Ответ 2
success · get_booking · HTTP 200
Бронь №102 принадлежит Josh Allen. Заезд 01-01-2018, выезд 01-01-2019. Предоплата внесена, особые пожелания: super bowls.
{'firstname': 'Josh', 'lastname': 'Allen', 'totalprice': 111, 'depositpaid': True, 'bookingdates': {'checkin': '2018-01-01', 'checkout': '2019-01-01'}, 'additionalneeds': 'super bowls'}

# Запрос 3
python main.py "найди все бронирования клиента Anonymous" 
# Ответ 3
success · list_bookings · HTTP 200
У клиента Anonymous пока нет забронированных номеров.
пусто

# Запрос 4
python main.py "создай бронь на 10 дней для клиента Big client"
# Ответ 4
needs_clarification · - · HTTP -
Уточните дату заезда и внесите ли вы предоплату?

# Запрос 5
python main.py "создай бронь на 10 дней для клиента Big client. Заезд 2027-02-14. Предоплата имеется. В номере нужен телевизоръ" 

Подтверждение create_booking: {"firstname": "Big", "lastname": "client", "totalprice": 1000, "depositpaid": true, "bookingdates": {"checkin": "2027-02-14", "checkout": "2027-02-24"}, 
"additionalneeds": "телевизор"}
Выполнить? [y/N]: Y
# Ответ 5
success · create_booking · HTTP 200
Бронирование создано. ID бронирования: 1264.
{
    'bookingid': 1264,
    'booking': {
        'firstname': 'Big',
        'lastname': 'client',
        'totalprice': 1000,
        'depositpaid': True,
        'bookingdates': {'checkin': '2027-02-14', 'checkout': '2027-02-24'},
        'additionalneeds': 'телевизор'
    }
}