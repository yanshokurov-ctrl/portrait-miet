"""Консольный интерфейс опроса (прототип этапа 1).

Только показывает вопросы и передаёт действия пользователя в движок.
Подсчёт баллов, порядок вопросов и проверка ответов — в ядре.

Ввод и вывод передаются параметрами (input_fn, print_fn), чтобы
интерфейс можно было проверять автотестами без настоящей консоли.
"""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path

from portrait.core.collector import collect, to_text
from portrait.core.contracts import METHODS
from portrait.core.engine import SurveySession
from portrait.core.errors import InvalidAnswerError, SessionError, SourceError
from portrait.core.models import Answer, Question, QuestionType
from portrait.sources.json_source import JsonSource

InputFn = Callable[[str], str]
PrintFn = Callable[..., None]

# Команды пользователя
CMD_SKIP = "п"
CMD_BACK = "н"
CMD_NEXT = "д"
CMD_STOP = "с"
CMD_HELP = "?"

HELP_TEXT = (
    "Как отвечать: введите номер варианта, число или текст — в зависимости от вопроса.\n"
    f"Команды: {CMD_SKIP} — пропустить вопрос, {CMD_BACK} — назад, "
    f"{CMD_NEXT} — дальше без изменения ответа, {CMD_STOP} — закончить опрос, {CMD_HELP} — помощь."
)


# ---------------------------------------------------------------------------
# Показ вопроса и разбор ответа
# ---------------------------------------------------------------------------


def format_answer(question: Question, answer: Answer) -> str:
    """Как показать уже данный ответ: «2 — Затрудняюсь ответить», «пропущен», «5»."""
    if answer.skipped:
        return "пропущен"
    for number, option in enumerate(question.options, start=1):
        if option.value == answer.value:
            return f"{number} — {option.label}"
    return str(answer.value)


def show_question(question: Question, number: int, total: int,
                  previous: Answer | None, print_fn: PrintFn) -> None:
    """Печатает вопрос: номер, текст, варианты и подсказку, как отвечать."""
    print_fn("")
    print_fn(f"Вопрос {number} из {total}")
    print_fn(question.text)
    if question.options:
        for option_number, option in enumerate(question.options, start=1):
            print_fn(f"  {option_number}) {option.label}")
    elif question.type == QuestionType.NUMBER:
        print_fn("  (введите число)")
    else:
        print_fn("  (введите ответ текстом)")
    if previous is not None:
        print_fn(f"  Ваш ответ: {format_answer(question, previous)}  ({CMD_NEXT} — оставить)")


def parse_answer(question: Question, text: str) -> int | float | str:
    """Переводит введённую строку в значение ответа.

    Для вопросов с вариантами пользователь вводит номер варианта (1, 2, 3...),
    а в движок уходит значение этого варианта. Если строка не подходит —
    InvalidAnswerError с подсказкой.
    """
    if question.options:
        if not text.isdigit() or not 1 <= int(text) <= len(question.options):
            raise InvalidAnswerError(f"Введите номер варианта от 1 до {len(question.options)}")
        return question.options[int(text) - 1].value

    if question.type == QuestionType.NUMBER:
        try:
            number = float(text.replace(",", "."))
        except ValueError:
            raise InvalidAnswerError("Нужно ввести число, например 5 или 2,5") from None
        return int(number) if number.is_integer() else number

    return text


# ---------------------------------------------------------------------------
# Прохождение опроса
# ---------------------------------------------------------------------------


def run_survey(session: SurveySession, input_fn: InputFn = input, print_fn: PrintFn = print) -> None:
    """Проводит пользователя по вопросам до конца опроса или до команды «закончить».

    Ctrl+C или конец ввода тоже завершают опрос: ответы, данные до этого,
    сохраняются и попадают в отчёт.
    """
    print_fn(HELP_TEXT)
    shown_method = None

    while not session.is_finished():
        question = session.current_question()
        if question.method_id != shown_method:
            shown_method = question.method_id
            print_fn("")
            print_fn(f"=== {METHODS[shown_method]} ===")

        progress = session.progress()
        show_question(question, progress.number, progress.total, session.current_answer(), print_fn)

        try:
            text = input_fn("> ").strip()
        except (EOFError, KeyboardInterrupt):
            print_fn("")
            print_fn("Опрос прерван. Ответы, данные до этого, сохранены.")
            return

        command = text.lower()
        try:
            if command == CMD_STOP:
                print_fn("Опрос завершён досрочно. Ответы, данные до этого, сохранены.")
                return
            elif command == CMD_SKIP:
                session.skip()
            elif command == CMD_BACK:
                session.back()
            elif command == CMD_NEXT:
                session.next()
            elif command == CMD_HELP:
                print_fn(HELP_TEXT)
            elif not text:
                print_fn(f"! Введите ответ или команду ({CMD_HELP} — помощь)")
            else:
                session.answer(parse_answer(question, text))
        except (InvalidAnswerError, SessionError) as error:
            # Недопустимый ответ или действие — сообщаем и задаём тот же вопрос снова
            print_fn(f"! {error}")


def run(methods_folder: str | Path | None = None, out_path: str | Path = "portrait.json",
        respondent_id: str | None = None,
        input_fn: InputFn = input, print_fn: PrintFn = print) -> int:
    """Полный сценарий: загрузка методик → опрос → подсчёт → отчёт на экран и в JSON.

    Возвращает код завершения программы: 0 — успешно, 1 — ошибка.
    """
    try:
        source = JsonSource(methods_folder) if methods_folder is not None else JsonSource()
        session = SurveySession(source.load_methods())
    except (SourceError, SessionError) as error:
        # Источник вопросов недоступен — понятное сообщение и остановка
        print_fn(f"Не удалось загрузить методики: {error}")
        return 1

    print_fn("ПОРТРЕТ ЛИЧНОСТИ — опрос")
    print_fn(f"Вопросов: {session.progress().total}")
    run_survey(session, input_fn, print_fn)

    portrait = collect(session.finish(), respondent_id)
    print_fn("")
    print_fn(to_text(portrait))

    try:
        Path(out_path).write_text(portrait.to_json() + "\n", encoding="utf-8")
    except OSError as error:
        print_fn("")
        print_fn(f"Не удалось сохранить результат в {out_path}: {error}")
        return 1

    print_fn("")
    print_fn(f"Результат сохранён в файл {out_path}")
    return 0
