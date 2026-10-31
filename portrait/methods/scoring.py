"""Подсчёт баллов по ключам методики.

Ключи описываются в JSON-файле методики, в разделе "scoring".
Номера вопросов в ключах — порядковые номера вопросов методики (с 1).

    "scoring": {
      "reverse_base": 6,            # для обратных пунктов: балл = reverse_base − ответ
      "note": "Текст-пояснение",    # необязательно: добавляется к интерпретации
      "scales": [ ... ],
      "interpretation": { ... }     # необязательно: вывод по шкалам
    }

Шкалы бывают трёх видов (у каждой есть "name"):

1. Сумма (или среднее) ответов по пунктам — ответы должны быть числами:
       {"name": "Самооценка", "items": [1, 2, 3, 4], "reverse": [2, 3, 4]}
       {"name": "Мотивы престижа", "items": [8, 9, 29], "aggregate": "mean"}

2. Совпадение с ключом — 1 балл за каждый ответ, совпавший с ключом:
       {"name": "Шкала лжи", "key": {"6": "да", "12": "да"}}

3. Составная — сумма (и разность) уже посчитанных шкал, объявленных выше:
       {"name": "Общий ЭИ", "plus": ["ВЭИ", "МЭИ"]}
       {"name": "ИОАД", "plus": ["ИОА"], "minus": ["ИОЭ"]}

Интерпретация "dominant": какая из шкал набрала больше всего баллов:
       {"type": "dominant", "scales": [...], "min": 4, "title": "Доминирующий стиль"}

Пропущенные и непройденные вопросы в подсчёт не попадают: сумма считается
по отвеченным пунктам, совпадения — только по отвеченным.
"""

from __future__ import annotations

from portrait.core.models import Question, ScaleScore

AGGREGATES = ("sum", "mean")


def _is_number(value: object) -> bool:
    return isinstance(value, (int, float)) and not isinstance(value, bool)


def _number(raw: object, total: int, where: str) -> int:
    """Номер вопроса из ключа: целое от 1 до total."""
    try:
        number = int(raw)
    except (TypeError, ValueError):
        raise ValueError(f"{where}: номер вопроса {raw!r} должен быть целым числом") from None
    if not 1 <= number <= total:
        raise ValueError(f"{where}: вопроса №{number} нет (в методике {total} вопросов)")
    return number


# ---------------------------------------------------------------------------
# Проверка ключей при загрузке методики
# ---------------------------------------------------------------------------


def validate_scoring(scoring: dict, questions: list[Question]) -> None:
    """Проверяет раздел "scoring" и выбрасывает ValueError с понятным текстом при ошибке.

    Проверяется всё, что можно проверить до опроса: номера вопросов существуют,
    у пунктов сумм числовые варианты ответа, значения ключей есть среди вариантов,
    составные шкалы ссылаются на шкалы, объявленные выше.
    """
    if not isinstance(scoring, dict):
        raise ValueError("scoring должен быть объектом { ... }")
    scales = scoring.get("scales")
    if not isinstance(scales, list) or not scales:
        raise ValueError("в scoring нет списка шкал scales")

    total = len(questions)
    known_names: list[str] = []

    for position, scale in enumerate(scales, start=1):
        name = scale.get("name") if isinstance(scale, dict) else None
        if not isinstance(name, str) or not name.strip():
            raise ValueError(f"шкала №{position}: нет названия name")
        where = f"шкала «{name}»"
        if name in known_names:
            raise ValueError(f"{where}: название повторяется")

        kinds = [kind for kind in ("items", "key", "plus") if kind in scale]
        if len(kinds) != 1:
            raise ValueError(f"{where}: должно быть ровно одно из полей items, key, plus")

        if "items" in scale:
            _validate_items_scale(scale, scoring, questions, where)
        elif "key" in scale:
            _validate_key_scale(scale, questions, where)
        else:
            for part in scale["plus"] + scale.get("minus", []):
                if part not in known_names:
                    raise ValueError(f"{where}: шкала «{part}» не объявлена выше")

        known_names.append(name)

    interpretation = scoring.get("interpretation")
    if interpretation is not None:
        if interpretation.get("type") != "dominant":
            raise ValueError(f"неизвестный тип интерпретации {interpretation.get('type')!r}")
        for part in interpretation.get("scales", []):
            if part not in known_names:
                raise ValueError(f"интерпретация: шкалы «{part}» нет")


def _validate_items_scale(scale: dict, scoring: dict, questions: list[Question], where: str) -> None:
    total = len(questions)
    items = [_number(item, total, where) for item in scale["items"]]
    if not items:
        raise ValueError(f"{where}: пустой список пунктов")
    if len(items) != len(set(items)):
        raise ValueError(f"{where}: пункты повторяются")

    reverse = [_number(item, total, where) for item in scale.get("reverse", [])]
    if not set(reverse) <= set(items):
        raise ValueError(f"{where}: обратные пункты должны входить в items")
    if reverse and not _is_number(scoring.get("reverse_base")):
        raise ValueError(f"{where}: есть обратные пункты, но не задан reverse_base")

    if scale.get("aggregate", "sum") not in AGGREGATES:
        raise ValueError(f"{where}: aggregate должен быть одним из {AGGREGATES}")

    for number in items:
        question = questions[number - 1]
        if not question.options or not all(_is_number(option.value) for option in question.options):
            raise ValueError(f"{where}: у вопроса №{number} варианты ответа должны быть числами")


def _validate_key_scale(scale: dict, questions: list[Question], where: str) -> None:
    key = scale["key"]
    if not isinstance(key, dict) or not key:
        raise ValueError(f"{where}: key должен быть непустым объектом {{номер: ответ}}")
    for raw_number, expected in key.items():
        number = _number(raw_number, len(questions), where)
        question = questions[number - 1]
        if question.options and expected not in [option.value for option in question.options]:
            raise ValueError(f"{where}: у вопроса №{number} нет варианта {expected!r}")


# ---------------------------------------------------------------------------
# Подсчёт
# ---------------------------------------------------------------------------


def compute_scores(scoring: dict, values: dict[int, object]) -> list[ScaleScore]:
    """Считает баллы по всем шкалам.

    values — ответы {номер вопроса (с 1): значение}; только отвеченные вопросы.
    Ключи должны быть уже проверены validate_scoring().
    """
    reverse_base = scoring.get("reverse_base")
    computed: dict[str, int | float] = {}
    scores = []

    for scale in scoring["scales"]:
        if "items" in scale:
            reverse = {int(item) for item in scale.get("reverse", [])}
            points = [
                reverse_base - values[int(item)] if int(item) in reverse else values[int(item)]
                for item in scale["items"] if int(item) in values
            ]
            if scale.get("aggregate") == "mean":
                raw = round(sum(points) / len(points), 2) if points else 0
            else:
                raw = sum(points)
        elif "key" in scale:
            raw = sum(1 for number, expected in scale["key"].items() if values.get(int(number)) == expected)
        else:
            raw = sum(computed[name] for name in scale["plus"]) - sum(computed[name] for name in scale.get("minus", []))

        computed[scale["name"]] = raw
        scores.append(ScaleScore(scale=scale["name"], raw=raw))

    return scores


def interpret(scoring: dict, scores: list[ScaleScore]) -> str:
    """Текстовый вывод по методике: пояснение (note) и, если задано, доминирующая шкала."""
    parts = []
    interpretation = scoring.get("interpretation")
    if interpretation is not None:
        parts.append(_dominant(interpretation, {score.scale: score.raw for score in scores}))
    if scoring.get("note"):
        parts.append(scoring["note"])
    return " ".join(parts)


def _dominant(interpretation: dict, raw_by_scale: dict[str, int | float]) -> str:
    """«Доминирующий стиль: …» — шкала с наибольшим баллом.

    Если лидеров несколько — они совмещаются. Если лидер один, но его балл
    ниже порога min — доминирующей шкалы нет.
    """
    title = interpretation.get("title", "Доминирующая шкала")
    candidates = {name: raw_by_scale[name] for name in interpretation["scales"]}
    best = max(candidates.values())
    leaders = [name for name, raw in candidates.items() if raw == best]
    if len(leaders) > 1:
        return f"{title}: совмещаются {', '.join(leaders)} (по {best} {points_word(best)})."
    if best < interpretation.get("min", 0):
        return f"{title}: не выражен (наибольший балл — {best})."
    return f"{title}: {leaders[0]} ({best} {points_word(best)})."


def points_word(number: int | float) -> str:
    """Склоняет слово «балл»: 1 балл, 2 балла, 5 баллов, 2.5 балла."""
    if isinstance(number, float) and not number.is_integer():
        return "балла"
    number = abs(int(number))
    if number % 10 == 1 and number % 100 != 11:
        return "балл"
    if 2 <= number % 10 <= 4 and not 12 <= number % 100 <= 14:
        return "балла"
    return "баллов"
