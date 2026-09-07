# Карта проекта для дальнейших изменений

Этот файл — короткая навигация по коду. Сначала открывайте нужный раздел здесь,
а не весь репозиторий целиком.

## Куда вносить изменения

| Задача | Файл или папка |
| --- | --- |
| Пользовательский текст, инструкция, сообщение об ошибке | `texts.py` |
| Общая кнопка/меню | `keyboards_parts/common.py` |
| Кнопки конкурса, мероприятий, архива, предложки, админки | соответствующий файл в `keyboards_parts/` |
| Сценарий входа и главное меню | `handlers/start.py`, `handlers/community.py` |
| Подача конкурсной работы | `handlers/contest.py` + `services/contests.py` |
| Конструктор, завершение и удаление конкурсов | `handlers/contest_admin.py` + `keyboards_parts/contest.py` |
| SQLite CRUD конкурсов | `services/contest_database.py` |
| Мероприятия и напоминания | `handlers/events.py` + `services/events.py` |
| Предложка и модерация листов | `handlers/publications.py` + `services/publications.py` |
| Экран очереди публикаций | `handlers/publication_queue.py` |
| Админские команды и диагностика | `handlers/admin.py` |
| SQLite-запросы и CRUD | `services/database.py` |
| Таблицы и миграции SQLite | `services/database_schema.py` |
| Проверки подписок и входа в группу | `services/subscriptions.py`, `services/community.py` |
| FSM-состояния | `states.py` |
| Переменные окружения и пути | `config.py`, `.env.example` |
| Сборка Dispatcher и фоновые циклы | `bot.py` |

## Важные контракты

1. **Callback-кнопка и обработчик связаны строкой.** При переименовании
   `callback_data` ищите старое значение одновременно в `keyboards_parts/` и
   `handlers/`. Для значений с ID сохраняйте формат `prefix:123`.
2. **FSM-сценарий — это цепочка состояний.** При добавлении шага изменяйте
   `states.py`, обработчик перехода и обработчик сообщения/кнопки для нового
   состояния. Не храните прогресс пользователя в глобальных переменных.
3. **Старая база Railway должна продолжать открываться.** Новую таблицу
   добавляйте в `SCHEMA_STATEMENTS`, новую колонку существующей таблицы — в
   `PROPOSED_POST_COMPAT_COLUMNS` с совместимым `DEFAULT` или `NULL`.
4. **Telegram-тексты и HTML — разные форматы.** Если меняется разметка
   публикаций, проверяйте `text_format`, `parse_mode` и экранирование в
   `services/publications.py`.
5. **Фоновые циклы должны переживать временный сбой.** Не выносите
   `try/except` наружу из `publication_loop` и `house_event_reminder_loop` без
   отдельной обработки ошибок.

## Безопасный порядок работы

1. Найти точку входа сценария в таблице выше.
2. Проверить соседние клавиатуры, тексты и FSM-состояния.
3. Если меняется SQL — сначала обновить `services/database_schema.py`, затем
   CRUD в `services/database.py`.
4. Не менять callback-строки, названия состояний и имена переменных окружения
   без поиска всех использований.
5. Запустить проверки:

```powershell
$env:PYTHONDONTWRITEBYTECODE = "1"
python -m unittest discover -s tests -v
python -c "import ast; from pathlib import Path; [ast.parse(p.read_text(encoding='utf-8'), filename=str(p)) for p in Path('.').rglob('*.py') if '__pycache__' not in p.parts]"
```

Комментарии в коде должны объяснять инвариант, ограничение Telegram/SQLite
или причину нетривиального решения. Очевидные строки не комментируем: так
навигация остаётся компактной и полезной для следующих изменений.
