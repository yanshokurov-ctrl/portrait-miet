"""Консольный интерфейс опроса (прототип).

Только показывает вопросы и передаёт действия пользователя в движок.
Подсчёт баллов, порядок вопросов и проверка ответов — в ядре.

Правила прохождения:
- каждая методика — отдельный тест: перед её вопросами показываются
  «Методика N из M» и инструкция (название методики по ТЗ не показывается);
- завершить опрос и получить результат можно только после того,
  как пройдены все методики;
- если опрос прерван (Ctrl+C, закрыт ввод), результат не сохраняется.

Ввод и вывод передаются параметрами (input_fn, print_fn), чтобы
интерфейс можно было проверять автотестами без настоящей консоли.
"""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path

from portrait.core.collector import collect, to_text
from portrait.core.engine import SurveySession
from portrait.core.errors import InvalidAnswerError, SessionError, SourceError
from portrait.core.models import Answer, Question, QuestionType
from portrait.sources.json_source import JsonSource

InputFn = Callable[[str], str]
PrintFn = Callable[..., None]

# Команды пользователя. Пропуска вопросов нет: на каждый вопрос нужно ответить.
CMD_BACK = "н"
CMD_FINISH = "з"
CMD_HELP = "?"

HELP_TEXT = (
    "Как отвечать: введите номер варианта, число или текст — в зависимости от вопроса.\n"
    f"Команды: {CMD_BACK} — назад к предыдущему вопросу, {CMD_HELP} — помощь.\n"
    f"Команда {CMD_FINISH} — завершить опрос — станет доступна, когда будут пройдены все методики."
)

SEPARATOR = "=" * 60


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


def show_method_header(number: int, total: int, instruction: str, print_fn: PrintFn) -> None:
    """Печатает заголовок методики: номер и инструкцию (без названия методики — по ТЗ)."""
    print_fn("")
    print_fn(SEPARATOR)
    print_fn(f"Методика {number} из {total}")
    if instruction:
        print_fn("")
        print_fn("Инструкция:")
        print_fn(instruction)
    print_fn(SEPARATOR)


def show_question(question: Question, number: int, total: int,
                  previous: Answer | None, print_fn: PrintFn, overall: str = "") -> None:
    """Печатает вопрос: номер, текст, варианты и подсказку, как отвечать."""
    print_fn("")
    print_fn(f"Вопрос {number} из {total}{overall}")
    print_fn(question.text)
    if question.options:
        for option_number, option in enumerate(question.options, start=1):
            print_fn(f"  {option_number}) {option.label}")
    elif question.type == QuestionType.NUMBER:
        print_fn("  (введите число)")
    else:
        print_fn("  (введите ответ текстом)")
    if previous is not None:
        print_fn(f"  Ваш прежний ответ: {format_answer(question, previous)} — введите ответ заново")


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


def run_survey(session: SurveySession, input_fn: InputFn = input, print_fn: PrintFn = print) -> bool:
    """Проводит пользователя по всем методикам.

    Возвращает True, если пользователь прошёл все методики и завершил опрос
    командой «з», и False, если опрос прерван (Ctrl+C или конец ввода).
    """
    print_fn(HELP_TEXT)
    shown_method = None

    while True:
        if session.is_finished():
            print_fn("")
            print_fn(SEPARATOR)
            print_fn("Все методики пройдены.")
            print_fn(f"{CMD_FINISH} — завершить опрос и получить результат, "
                     f"{CMD_BACK} — вернуться к последнему вопросу")
            print_fn(SEPARATOR)
            shown_method = None  # после возврата назад снова покажем заголовок методики
        else:
            question = session.current_question()
            method_progress = session.method_progress()
            if question.method_id != shown_method:
                shown_method = question.method_id
                show_method_header(method_progress.number, method_progress.total,
                                   session.current_method().instruction, print_fn)
            progress = session.progress()
            show_question(question, method_progress.question_number, method_progress.question_total,
                          session.current_answer(), print_fn,
                          overall=f"   (всего: {progress.number} из {progress.total})")

        try:
            text = input_fn("> ").strip()
        except (EOFError, KeyboardInterrupt):
            print_fn("")
            print_fn("Опрос прерван.")
            return False

        command = text.lower()
        try:
            if command == CMD_FINISH:
                if not session.is_finished():
                    raise SessionError("Завершить опрос можно только после того, как пройдены все методики")
                return True
            elif command == CMD_BACK:
                session.back()
            elif command == CMD_HELP:
                print_fn(HELP_TEXT)
            elif session.is_finished():
                print_fn(f"! Введите {CMD_FINISH}, чтобы завершить опрос, или {CMD_BACK}, чтобы вернуться назад")
            elif not text:
                print_fn(f"! Введите ответ или команду ({CMD_HELP} — помощь)")
            else:
                session.answer(parse_answer(session.current_question(), text))
        except (InvalidAnswerError, SessionError) as error:
            # Недопустимый ответ или действие — сообщаем и задаём тот же вопрос снова
            print_fn(f"! {error}")


def run(methods_folder: str | Path | None = None, out_path: str | Path = "portrait.json",
        respondent_id: str | None = None,
        input_fn: InputFn = input, print_fn: PrintFn = print) -> int:
    """Полный сценарий: загрузка методик → опрос → подсчёт → отчёт на экран и в JSON.

    Возвращает код завершения программы: 0 — успешно, 1 — ошибка или опрос прерван.
    """
    try:
        source = JsonSource(methods_folder) if methods_folder is not None else JsonSource()
        session = SurveySession(source.load_methods())
    except (SourceError, SessionError) as error:
        # Источник вопросов недоступен — понятное сообщение и остановка
        print_fn(f"Не удалось загрузить методики: {error}")
        return 1

    total_methods = session.method_progress().total if not session.is_finished() else 0
    print_fn("ПОРТРЕТ ЛИЧНОСТИ — опрос")
    print_fn(f"Методик: {total_methods}, вопросов: {session.progress().total}")

    if not run_survey(session, input_fn, print_fn):
        print_fn("Результат не сохранён: опрос нужно пройти до конца.")
        return 1

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
