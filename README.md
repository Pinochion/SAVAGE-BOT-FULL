# SAVAGE BOT

Основа: SAVAGE-BOT TICKETS. Система профилей удалена.

## Модули
- `cogs/tickets.py` — тикеты и заявки.
- `cogs/warns.py` — WARN.
- `cogs/admin_panel.py` — единая админ-панель.
- `cogs/contracts.py` — контракты, пик 15 минут.
- `cogs/reactions.py` — наборы на контент с приоритетом MAIN > DEFAULT > ACADEMY.
- `utils/config_db.py` — общая конфигурация и БД новых систем.

## Запуск
1. `python -m venv .venv`
2. активировать venv
3. `pip install -r requirements.txt`
4. скопировать `.env.example` в `.env`
5. заполнить `DISCORD_TOKEN` и `GUILD_ID`
6. `python main.py`

## Первичная настройка
Администратор использует `/admin-panel`. В панели задаются роли и каналы. После настройки можно опубликовать панели:
- `/ticket send-panel`
- `/contracts-panel`
- `/reactions start`

## Примечание
Существующие команды настройки тикетов и WARN сохранены для обратной совместимости. Основной способ настройки — новая админ-панель.
