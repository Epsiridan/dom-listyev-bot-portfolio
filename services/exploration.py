# -*- coding: utf-8 -*-
"""Бизнес-логика исследований комнат и личного журнала."""

import random
import re
from dataclasses import dataclass
from datetime import datetime, timedelta

from config import settings

ROOM_EXPLORATION_COOLDOWN = timedelta(hours=6)
ROOM_REVISIT_WINDOW = timedelta(hours=48)
ROOM_NAME_MAX_LENGTH = 80
RARITY_WEIGHTS = {
    "ordinary": 40,
    "rare": 8,
    "unique": 1,
}
EXPECTED_RARITY_COUNTS = {
    "ordinary": 18,
    "rare": 5,
    "unique": 2,
}
COMMAND_RE = re.compile(
    r"^/(?:исследовать(?:@\w+)?\s+комнату|исследуй(?:@\w+)?(?:\s+комнату)?)(?:\s+(.+))?$",
    re.IGNORECASE | re.DOTALL,
)


@dataclass(frozen=True, slots=True)
class ObservationOption:
    """Один взвешенный вариант наблюдения."""

    text: str
    rarity: str = "ordinary"

    @property
    def weight(self) -> int:
        return RARITY_WEIGHTS[self.rarity]


@dataclass(frozen=True, slots=True)
class RoomIdentity:
    """Нормализованный ключ комнаты и имя для показа."""

    key: str
    display_name: str
    special_key: str | None = None


@dataclass(frozen=True, slots=True)
class ExplorationReport:
    """Три независимых аспекта исследования и необязательная приписка."""

    space: str
    traces: str
    response: str
    revisit_note: str | None = None


SPACE_OBSERVATIONS: tuple[ObservationOption, ...] = (
    ObservationOption("Размеры совпадают с планом, хотя рулетка дважды зацепилась за пустое место."),
    ObservationOption("Все четыре угла находятся на своих местах и хорошо просматриваются."),
    ObservationOption("Температура почти не отличается от коридора."),
    ObservationOption("Воздух сухой и пахнет старой бумагой и деревом."),
    ObservationOption("Освещение ровное; тени меняются только вслед за смотрителем."),
    ObservationOption("Пол имеет едва заметный уклон в сторону двери."),
    ObservationOption("Потолок возвращает звук с небольшой, но допустимой задержкой."),
    ObservationOption("Стены поглощают шаги лучше, чем ожидалось."),
    ObservationOption("Дверь остаётся видна из любой проверенной точки."),
    ObservationOption("Из коридора тянет прохладным сквозняком."),
    ObservationOption("После минуты внутри свет становится немного теплее."),
    ObservationOption("Повторное измерение дало тот же результат с точностью до сантиметра."),
    ObservationOption("Пыль собралась преимущественно в дальних углах."),
    ObservationOption("Комната выглядит чуть меньше, чем обещает её название."),
    ObservationOption("Половицы отзываются в устойчивой последовательности."),
    ObservationOption("В центре помещения неожиданно хорошая акустика."),
    ObservationOption("Поверхности холодные, но не влажные."),
    ObservationOption("План не требует исправлений; смотритель всё равно оставил место для примечания."),
    ObservationOption("Дальняя стена кажется ближе, чем во время первого измерения.", "rare"),
    ObservationOption("Один из углов удаётся увидеть только боковым зрением.", "rare"),
    ObservationOption("Потолок оказался выше значения, указанного в плане.", "rare"),
    ObservationOption("Свет не достигает небольшого участка в центре комнаты.", "rare"),
    ObservationOption("Коридор за открытой дверью выглядит длиннее, чем снаружи.", "rare"),
    ObservationOption("Количество выходов изменилось между двумя измерениями.", "unique"),
    ObservationOption("План помещения обновился раньше, чем смотритель закончил запись.", "unique"),
)

TRACE_OBSERVATIONS: tuple[ObservationOption, ...] = (
    ObservationOption("Следов недавнего пребывания не обнаружено."),
    ObservationOption("Пыль нарушена только у самого порога."),
    ObservationOption("У плинтуса лежит один сухой лист."),
    ObservationOption("На стене сохранилась старая карандашная отметка."),
    ObservationOption("В щели пола застряла короткая зелёная нить."),
    ObservationOption("На поверхности остался круглый след от чашки."),
    ObservationOption("На половице заметна неглубокая царапина, ведущая к выходу."),
    ObservationOption("Найден чистый обрывок бумаги без водяных знаков."),
    ObservationOption("На дверной раме виден старый след от связки ключей."),
    ObservationOption("В углу застыла маленькая капля воска."),
    ObservationOption("В стене обнаружены три аккуратных отверстия от гвоздей."),
    ObservationOption("Между досками пола сохранился спрессованный лист."),
    ObservationOption("На обороте плинтуса стоит инвентарный номер."),
    ObservationOption("Единственный старый след обуви направлен к двери."),
    ObservationOption("На подоконной пыли виден отпечаток ладони, почти стёртый временем."),
    ObservationOption("В воздухе ненадолго появился запах свежего графита."),
    ObservationOption("Один предмет сдвинут ровно настолько, чтобы это можно было списать на уборку."),
    ObservationOption("Всё видимое соответствует описи, включая пустое место в конце списка."),
    ObservationOption("На пыли обнаружена одна свежая линия.", "rare"),
    ObservationOption("Один из найденных предметов оказался тёплым.", "rare"),
    ObservationOption("Найден ключ, не подходящий ни к одной проверенной двери.", "rare"),
    ObservationOption("В журнале есть запись без даты и подписи.", "rare"),
    ObservationOption("На клочке бумаги нарисованы три двери, соединённые одной линией.", "rare"),
    ObservationOption("Следы начинаются в центре комнаты и не ведут ко входу.", "unique"),
    ObservationOption("В описи указан предмет, который смотритель всё это время держал в руках.", "unique"),
)

RESPONSE_OBSERVATIONS: tuple[ObservationOption, ...] = (
    ObservationOption("Дом не проявил заметной реакции на осмотр."),
    ObservationOption("Дверь оставалась открытой до окончания исследования."),
    ObservationOption("Посторонних звуков не зафиксировано."),
    ObservationOption("Комната закрылась без происшествий."),
    ObservationOption("Ключ повернулся один раз и без усилия."),
    ObservationOption("После выхода обычный шум коридора вернулся сразу."),
    ObservationOption("Освещение не изменилось до самого ухода."),
    ObservationOption("Сквозняк прекратился одновременно с закрытием двери."),
    ObservationOption("Последний шаг прозвучал тише предыдущих."),
    ObservationOption("Ручка двери осталась прохладной."),
    ObservationOption("Запись удалось закончить ещё внутри комнаты."),
    ObservationOption("После закрытия номер комнаты остался прежним."),
    ObservationOption("Дом принял запись без дополнительных замечаний."),
    ObservationOption("Связка ключей перестала звенеть у самого порога."),
    ObservationOption("На выходе смотритель пересчитал инструменты; всё оказалось на месте."),
    ObservationOption("Дверь закрылась со второго раза, как и большинство старых дверей."),
    ObservationOption("Чернила в журнале высохли необычно быстро, но ровно."),
    ObservationOption("Через минуту после ухода внутри по-прежнему было тихо."),
    ObservationOption("Перед уходом лампа один раз мигнула.", "rare"),
    ObservationOption("Замок закрылся раньше, чем в него вставили ключ.", "rare"),
    ObservationOption("После выхода внутри послышался ещё один шаг.", "rare"),
    ObservationOption("Номер комнаты пришлось проверить повторно.", "rare"),
    ObservationOption("Под дверью на мгновение появилась полоска света другого цвета.", "rare"),
    ObservationOption("Итоговая запись появилась в журнале до начала исследования.", "unique"),
    ObservationOption("После закрытия дверь оказалась с другой стороны коридора.", "unique"),
)

OBSERVATION_TABLES = {
    "space": SPACE_OBSERVATIONS,
    "traces": TRACE_OBSERVATIONS,
    "response": RESPONSE_OBSERVATIONS,
}

for table_name, table in OBSERVATION_TABLES.items():
    rarity_counts = {
        rarity: sum(option.rarity == rarity for option in table)
        for rarity in EXPECTED_RARITY_COUNTS
    }
    if len(table) != 25 or rarity_counts != EXPECTED_RARITY_COUNTS:
        raise RuntimeError(
            f"Некорректная таблица {table_name}: вариантов={len(table)}, редкости={rarity_counts}"
        )


SPECIAL_ROOM_NAMES = {
    "workshop": "Мастерская",
    "hall": "Холл",
    "bedroom": "Спальня",
}
SPECIAL_ROOM_ALIASES = {
    "мастерская": "workshop",
    "мастерскую": "workshop",
    "писательская мастерская": "workshop",
    "холл": "hall",
    "зал": "hall",
    "вестибюль": "hall",
    "спальня": "bedroom",
    "спальню": "bedroom",
}

SPECIAL_ROOM_POOLS: dict[str, dict[str, tuple[ObservationOption, ...]]] = {
    "workshop": {
        "space": (
            ObservationOption("Письменный стол обращён к стене, на которой удобно представлять окно."),
            ObservationOption("Полки слегка прогибаются под рукописями, хотя большинство папок пусты."),
            ObservationOption("Узкая полоса света лежит точно поперёк чистой страницы."),
        ),
        "traces": (
            ObservationOption("В закрытой чернильнице обнаружены свежие чернила."),
            ObservationOption("В корзине лежит начало рассказа, перечёркнутое разными почерками."),
            ObservationOption("На полях оставлена приписка: сначала ищут место, через которое проходят все двери.", "unique"),
        ),
        "response": (
            ObservationOption("После выхода одна клавиша печатной машинки нажалась сама."),
            ObservationOption("Последняя страница перевернулась, когда дверь уже закрывали."),
            ObservationOption("В незаконченной строке после слова Холл появилось длинное тире.", "rare"),
        ),
    },
    "hall": {
        "space": (
            ObservationOption("Расстояние от центра холла до каждой двери оказалось почти одинаковым."),
            ObservationOption("Узор из листьев на полу незаметно поворачивается в сторону мастерской.", "rare"),
            ObservationOption("Зеркало отражает на одну дверь больше, чем находится в стенах.", "unique"),
        ),
        "traces": (
            ObservationOption("На полу сходятся следы из нескольких коридоров, но ни один не пересекает центр."),
            ObservationOption("В книге посетителей оставлены три пустые строки подряд."),
            ObservationOption("Три сухих листа лежат у порога, у чернильного пятна и рядом с белым пером.", "unique"),
        ),
        "response": (
            ObservationOption("После осмотра замки щёлкнули по кругу, начиная от входной двери."),
            ObservationOption("Лампа над проходом к мастерской зажглась на несколько секунд.", "rare"),
            ObservationOption("Одна дверь открылась только после того, как две другие были закрыты.", "rare"),
        ),
    },
    "bedroom": {
        "space": (
            ObservationOption("Кровать стоит так, будто её передвинули, чтобы освободить место у стены."),
            ObservationOption("Узор листьев на обоях становится отчётливее в полумраке."),
            ObservationOption("Темнота под кроватью не меняется при перемещении лампы.", "rare"),
        ),
        "traces": (
            ObservationOption("На подушке сохранилось неглубокое углубление."),
            ObservationOption("Между страницами книги лежит лист с тремя прожилками."),
            ObservationOption("На обороте изголовья написано: последнее читают только после того, как закончен путь.", "unique"),
        ),
        "response": (
            ObservationOption("После ухода покрывало едва заметно выровнялось."),
            ObservationOption("Часы остановились на третьем щелчке закрывающегося замка.", "rare"),
            ObservationOption("Из комнаты донеслось три тихих стука; последний прозвучал из стены.", "unique"),
        ),
    },
}

SPECIAL_ROOM_REVISIT_NOTES = {
    "workshop": (
        "В оставленной ранее строке появилось ещё одно слово.",
        "Чернильное пятно стало похоже на план коридоров.",
        "Один из чистых листов теперь пронумерован.",
    ),
    "hall": (
        "Одна из дверей носит след от недавно использованного ключа.",
        "Узор на полу повернулся ещё на несколько градусов.",
        "В книге посетителей заполнена одна из трёх пустых строк.",
    ),
    "bedroom": (
        "Углубление на подушке стало глубже.",
        "Книга лежит раскрытой на другой странице.",
        "Один из трёх стуков теперь отмечен карандашом на стене.",
    ),
}

REVISIT_NOTES: tuple[str, ...] = (
    "Меловая отметка прошлого визита сохранилась, но стала бледнее.",
    "Дверная ручка заметно теплее, чем в прошлый раз.",
    "Один из прежних следов исчез, хотя пыль вокруг не потревожена.",
    "Ключ входит в замок легче, чем при предыдущем посещении.",
    "В журнале рядом с прошлой записью появилась короткая черта.",
    "Сквозняк начинается именно там, где смотритель стоял в прошлый раз.",
    "Сухой лист у порога сменил положение.",
    "На двери остался слабый отпечаток прежней меловой метки.",
    "Комната встретила смотрителя знакомым запахом, которого раньше не было в коридоре.",
    "Предыдущая запись выглядит старше остальных страниц журнала.",
    "Один звук повторился в той же последовательности, что и в прошлый раз.",
    "После ухода в кармане обнаружилась пылинка цвета местных стен.",
)


def extract_room_name(text: str | None) -> str | None:
    """Достать название комнаты из команды или вернуть None."""
    if not text:
        return None
    match = COMMAND_RE.match(text.strip())
    if not match:
        return None
    room_name = " ".join((match.group(1) or "").split())
    if not room_name:
        return ""
    return room_name[:ROOM_NAME_MAX_LENGTH]


def normalize_room_name(room_name: str) -> RoomIdentity:
    """Объединить регистр, пробелы, кавычки и алиасы специальных комнат."""
    cleaned = " ".join(room_name.strip().strip("«»\"'").split())
    cleaned = cleaned[:ROOM_NAME_MAX_LENGTH]
    folded = cleaned.casefold().replace("ё", "е")
    special_key = SPECIAL_ROOM_ALIASES.get(folded)
    if special_key is not None:
        return RoomIdentity(
            key=f"special:{special_key}",
            display_name=SPECIAL_ROOM_NAMES[special_key],
            special_key=special_key,
        )
    return RoomIdentity(key=folded, display_name=cleaned)


def _choose_option(options: tuple[ObservationOption, ...]) -> str:
    return random.choices(
        options,
        weights=[option.weight for option in options],
        k=1,
    )[0].text


def choose_exploration_report(room: RoomIdentity) -> ExplorationReport:
    """Выбрать три согласуемых аспекта, гарантируя характер специальной комнаты."""
    selected = {
        aspect: _choose_option(options)
        for aspect, options in OBSERVATION_TABLES.items()
    }

    if room.special_key is not None:
        special_pools = SPECIAL_ROOM_POOLS[room.special_key]
        guaranteed_aspect = random.choice(tuple(special_pools))
        for aspect, options in special_pools.items():
            if aspect == guaranteed_aspect or random.random() < 0.35:
                selected[aspect] = _choose_option(options)

    return ExplorationReport(
        space=selected["space"],
        traces=selected["traces"],
        response=selected["response"],
    )


def format_exploration_report(
    room: RoomIdentity,
    report: ExplorationReport,
) -> str:
    """Собрать атмосферный итог без зависимости между строками."""
    lines = [
        f"Комната «{room.display_name}».",
        "",
        f"Пространство: {report.space}",
        f"Следы: {report.traces}",
        f"Отклик Дома: {report.response}",
    ]
    if report.revisit_note:
        lines.extend(["", f"Приписка смотрителя: {report.revisit_note}"])
    return "\n".join(lines)


def format_remaining_cooldown(remaining: timedelta) -> str:
    """Сформатировать оставшийся кулдаун."""
    total_minutes = max(1, int((remaining.total_seconds() + 59) // 60))
    hours, minutes = divmod(total_minutes, 60)
    if hours and minutes:
        return f"{hours} ч. {minutes} мин."
    if hours:
        return f"{hours} ч."
    return f"{minutes} мин."


def _as_moscow_datetime(value: datetime) -> datetime:
    """Нормализовать старую naive-дату и новую aware-дату."""
    if value.tzinfo is None or value.utcoffset() is None:
        return value.replace(tzinfo=settings.MOSCOW_TZ)
    return value.astimezone(settings.MOSCOW_TZ)


def get_cooldown_remaining(
    last_explored_at: str | None,
    *,
    now: datetime | None = None,
) -> timedelta | None:
    """Посчитать ожидание; повреждённую запись считать отсутствующей."""
    if not last_explored_at:
        return None
    try:
        last_dt = _as_moscow_datetime(datetime.fromisoformat(last_explored_at))
    except (TypeError, ValueError):
        return None
    current_dt = _as_moscow_datetime(now or datetime.now(settings.MOSCOW_TZ))
    next_available_at = last_dt + ROOM_EXPLORATION_COOLDOWN
    if current_dt >= next_available_at:
        return None
    return next_available_at - current_dt


def choose_revisit_note(
    previous_explored_at: str | None,
    *,
    special_key: str | None = None,
    now: datetime | None = None,
) -> str | None:
    """Вернуть последствие повторного визита, если прошло не более 48 часов."""
    if not previous_explored_at:
        return None
    try:
        previous = _as_moscow_datetime(datetime.fromisoformat(previous_explored_at))
    except (TypeError, ValueError):
        return None

    current = _as_moscow_datetime(now or datetime.now(settings.MOSCOW_TZ))
    elapsed = current - previous
    if elapsed < timedelta(0) or elapsed > ROOM_REVISIT_WINDOW:
        return None

    if special_key is not None and random.random() < 0.5:
        return random.choice(SPECIAL_ROOM_REVISIT_NOTES[special_key])
    return random.choice(REVISIT_NOTES)
