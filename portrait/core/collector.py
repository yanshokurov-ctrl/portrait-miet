"""Сборщик результатов.

Принимает результаты методик (обычно — SurveySession.finish()) и собирает
итоговый «Портрет личности»: ровно 20 позиций в порядке справочника METHODS,
без потерь и дублей. Все проблемы с результатами видны в самом отчёте:
у методики статус ERROR или NO_DATA, в portrait.warnings — пояснение.

Правила:
- результат опознаётся по method_id; методики нет в справочнике — результат отброшен;
- повторный результат той же методики — отброшен, оставлен первый;
- результат в неверном формате — методика получает статус ERROR;
- название методики не совпадает со справочником — берётся из справочника;
- методика без результата — статус NO_DATA («Результат не получен»).

Пример:

    portrait = collect(session.finish())
    print(to_text(portrait))
    Path("portrait.json").write_text(portrait.to_json(), encoding="utf-8")
"""

from __future__ import annotations

import dataclasses
import uuid

from portrait.core.contracts import METHODS
from portrait.core.errors import InvalidResultError
from portrait.core.models import MethodResult, Portrait, ScaleScore, Status

# Как статусы называются в отчёте для пользователя
STATUS_TITLES = {
    Status.OK: "готово",
    Status.PARTIAL: "частично",
    Status.ERROR: "ошибка",
    Status.NO_DATA: "нет данных",
}


def new_respondent_id() -> str:
    """Создаёт анонимный id респондента, например «anon-1a2b3c4d»."""
    return f"anon-{uuid.uuid4().hex[:8]}"


# ---------------------------------------------------------------------------
# Сборка
# ---------------------------------------------------------------------------


def collect(results: list, respondent_id: str | None = None) -> Portrait:
    """Собирает «Портрет личности» из результатов методик.

    results       — список результатов в любом порядке (могут быть и неверные объекты);
    respondent_id — id респондента; если не указан, создаётся анонимный.

    Входной список и сами результаты не изменяются.
    """
    warnings: list[str] = []
    accepted: dict[str, MethodResult] = {}

    for position, result in enumerate(results, start=1):
        method_id = _guess_method_id(result)

        if method_id is None:
            warnings.append(f"Результат №{position}: не удалось определить методику "
                            f"({type(result).__name__}) — результат отброшен")
            continue
        if method_id not in METHODS:
            warnings.append(f"{method_id}: методики нет в справочнике — результат отброшен")
            continue
        if method_id in accepted:
            warnings.append(f"{method_id}: повторный результат отброшен, оставлен первый")
            continue

        try:
            validate_result(result)
        except InvalidResultError as error:
            warnings.append(f"{method_id}: результат в неверном формате — {error}")
            accepted[method_id] = MethodResult.error(method_id, METHODS[method_id],
                                                     f"Результат в неверном формате: {error}")
            continue

        if result.method_name != METHODS[method_id]:
            warnings.append(f"{method_id}: название «{result.method_name}» заменено "
                            f"на название из справочника")
            result = dataclasses.replace(result, method_name=METHODS[method_id])

        accepted[method_id] = result

    final_results = [
        accepted.get(method_id) or MethodResult.no_data(method_id, name, "Результат не получен")
        for method_id, name in METHODS.items()
    ]
    return Portrait(respondent_id=respondent_id or new_respondent_id(),
                    results=final_results, warnings=warnings)


def _guess_method_id(result: object) -> str | None:
    """Пытается узнать, к какой методике относится результат (даже если формат неверный)."""
    if isinstance(result, dict):
        method_id = result.get("method_id")
    else:
        method_id = getattr(result, "method_id", None)
    return method_id if isinstance(method_id, str) and method_id else None


def validate_result(result: object) -> None:
    """Проверяет формат результата методики.

    MethodResult проверяет себя при создании, но поля можно испортить позже,
    а методика может вернуть вообще не MethodResult. Поэтому сборщик
    перепроверяет всё. При проблемах — InvalidResultError со списком проблем.
    """
    if not isinstance(result, MethodResult):
        raise InvalidResultError(f"получен {type(result).__name__} вместо MethodResult")

    problems = []
    if not isinstance(result.method_name, str):
        problems.append("method_name должно быть строкой")
    if not isinstance(result.status, Status):
        problems.append(f"неизвестный статус {result.status!r}")
    if not isinstance(result.scores, list) or not all(isinstance(score, ScaleScore) for score in result.scores):
        problems.append("scores должен быть списком ScaleScore")
    if not isinstance(result.interpretation, str):
        problems.append("interpretation должно быть строкой")
    if not isinstance(result.errors, list) or not all(isinstance(error, str) for error in result.errors):
        problems.append("errors должен быть списком строк")

    counts_ok = True
    for field_name in ("answered", "total"):
        value = getattr(result, field_name)
        if not isinstance(value, int) or isinstance(value, bool) or value < 0:
            problems.append(f"{field_name} должно быть целым числом не меньше 0")
            counts_ok = False
    if counts_ok and result.answered > result.total:
        problems.append(f"отвечено ({result.answered}) больше, чем вопросов ({result.total})")

    if result.status in (Status.OK, Status.PARTIAL) and not result.scores:
        problems.append(f"при статусе {result.status} нужны баллы (scores)")

    if problems:
        raise InvalidResultError("; ".join(problems))


# ---------------------------------------------------------------------------
# Экспорт в текст
# ---------------------------------------------------------------------------


def _format_number(value: int | float) -> str:
    """6.0 → «6», 7.25 → «7.25»."""
    if isinstance(value, float) and value.is_integer():
        return str(int(value))
    return str(value)


def to_text(portrait: Portrait) -> str:
    """Переводит «Портрет личности» в читаемый текст для экрана или файла.

    Методики с результатом показываются подробно, методики без данных —
    коротким списком в конце, чтобы отчёт не растягивался.
    """
    summary = portrait.summary()
    lines = [
        "ПОРТРЕТ ЛИЧНОСТИ",
        f"Респондент: {portrait.respondent_id}",
        f"Дата: {portrait.created_at.replace('T', ' ')}",
        "",
        f"Методик: {len(portrait.results)} — готово {summary['ok']}, частично {summary['partial']}, "
        f"ошибок {summary['error']}, нет данных {summary['no_data']}",
    ]

    no_data_lines = []
    for number, result in enumerate(portrait.results, start=1):
        if result.status == Status.NO_DATA:
            reason = f" — {result.errors[0]}" if result.errors else ""
            no_data_lines.append(f"  {number}. {result.method_name}{reason}")
            continue

        lines.append("")
        header = f"{number}. {result.method_name} — {STATUS_TITLES[result.status]}"
        if result.total:
            header += f", отвечено {result.answered} из {result.total}"
        lines.append(header)

        for score in result.scores:
            level = f" (уровень: {score.level})" if score.level else ""
            lines.append(f"   {score.scale}: {_format_number(score.raw)}{level}")
        if result.interpretation:
            lines.append(f"   {result.interpretation}")
        if result.status == Status.PARTIAL:
            lines.append("   Часть вопросов пропущена — результат приблизительный.")
        if result.status == Status.ERROR:
            for error in result.errors:
                lines.append(f"   Причина: {error}")

    if no_data_lines:
        lines += ["", "Нет данных:"] + no_data_lines

    if portrait.warnings:
        lines += ["", "Предупреждения:"] + [f"  - {warning}" for warning in portrait.warnings]

    return "\n".join(lines)
