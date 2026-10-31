"""Тесты консольного интерфейса (portrait/ui/console.py) и сквозного прогона.

Ввод пользователя подменяется списком строк, вывод собирается в список,
поэтому тесты не требуют настоящей консоли.
Основные тесты идут на небольших тестовых методиках (tests/fixtures/methods:
m01–m03, по 3 вопроса), последний — на всех 20 настоящих методиках.
"""

import io
import json
import tempfile
import unittest
from contextlib import redirect_stdout
from pathlib import Path

from main import main
from portrait.core.contracts import METHODS
from portrait.core.engine import SurveySession
from portrait.core.errors import InvalidAnswerError
from portrait.core.models import Answer, Option, Question, QuestionType, Status
from portrait.sources.json_source import JsonSource
from portrait.ui.console import parse_answer, run, run_survey

FIXTURES = Path(__file__).parent / "fixtures" / "methods"

# Ответы на все вопросы тестовых методик: m01 (3 шкалы), m02 (выбор, число, шкала), m03 (шкала, выбор, текст)
FULL_INPUT = ["1", "2", "3", "1", "4", "3", "2", "1", "Взвешиваю за и против"]
FINISH = "з"


class FakeConsole:
    """Подменяет input/print: отдаёт заготовленные строки и запоминает вывод."""

    def __init__(self, lines):
        self.lines = list(lines)
        self.output = []

    def input(self, prompt=""):
        if not self.lines:
            raise EOFError
        return self.lines.pop(0)

    def print(self, *parts):
        self.output.append(" ".join(str(part) for part in parts))

    @property
    def text(self):
        return "\n".join(self.output)


def new_session():
    return SurveySession(JsonSource(FIXTURES).load_methods())


class ParseAnswerTests(unittest.TestCase):

    def setUp(self):
        self.choice = Question("m02_q01", "m02", "Да или нет?", 1, QuestionType.CHOICE,
                               [Option("да", "Да"), Option("нет", "Нет")])
        self.number = Question("m02_q02", "m02", "Сколько?", 2, QuestionType.NUMBER)
        self.text = Question("m03_q03", "m03", "Опишите", 3, QuestionType.TEXT)

    def test_option_number_gives_option_value(self):
        self.assertEqual(parse_answer(self.choice, "2"), "нет")

    def test_wrong_option_number(self):
        for text in ("0", "3", "да", "-1"):
            with self.subTest(text=text), self.assertRaises(InvalidAnswerError):
                parse_answer(self.choice, text)

    def test_numbers(self):
        self.assertEqual(parse_answer(self.number, "5"), 5)
        self.assertEqual(parse_answer(self.number, "2,5"), 2.5)
        self.assertEqual(parse_answer(self.number, "-3"), -3)
        with self.assertRaises(InvalidAnswerError):
            parse_answer(self.number, "пять")

    def test_text(self):
        self.assertEqual(parse_answer(self.text, "Свой ответ"), "Свой ответ")


class RunSurveyTests(unittest.TestCase):

    def run_with(self, lines):
        session = new_session()
        console = FakeConsole(lines)
        completed = run_survey(session, console.input, console.print)
        return session, console, completed

    def test_full_survey(self):
        session, console, completed = self.run_with(FULL_INPUT + [FINISH])
        self.assertTrue(completed)
        results = session.finish()
        self.assertEqual([result.status for result in results], [Status.OK] * 3)
        self.assertEqual(results[0].scores[0].raw, 6)   # 1 + 2 + 3

    def test_method_header_with_number_and_instruction(self):
        _, console, _ = self.run_with(FULL_INPUT + [FINISH])
        self.assertIn("Методика 1 из 3", console.text)
        self.assertIn("Методика 3 из 3", console.text)
        self.assertIn("Инструкция:\nТестовая инструкция первой методики.", console.text)

    def test_method_names_not_shown(self):
        # ТЗ: название методики респонденту не показывается
        _, console, _ = self.run_with(FULL_INPUT + [FINISH])
        for method_id in ("m01", "m02", "m03"):
            self.assertNotIn(METHODS[method_id], console.text)

    def test_question_numbers_inside_method_and_overall(self):
        _, console, _ = self.run_with(FULL_INPUT + [FINISH])
        self.assertIn("Вопрос 1 из 3   (всего: 1 из 9)", console.text)
        self.assertIn("Вопрос 3 из 3   (всего: 9 из 9)", console.text)

    def test_finish_not_allowed_before_end(self):
        session, console, completed = self.run_with([FINISH, "1", FINISH] + FULL_INPUT[1:] + [FINISH])
        self.assertEqual(console.text.count("! Завершить опрос можно только после того, как пройдены все методики"), 2)
        self.assertTrue(completed)
        self.assertEqual(session.grouped_answers()["m01"]["m01_q01"].value, 1)  # «з» не сбила ответы

    def test_end_screen_waits_for_finish(self):
        _, console, completed = self.run_with(FULL_INPUT + ["1", FINISH])
        self.assertIn("Все методики пройдены.", console.text)
        self.assertIn("! Введите з, чтобы завершить опрос", console.text)
        self.assertTrue(completed)

    def test_back_from_end_screen_and_change_answer(self):
        session, console, completed = self.run_with(FULL_INPUT + ["н", "Другой ответ", FINISH])
        self.assertIn("Ваш прежний ответ: Взвешиваю за и против", console.text)
        self.assertEqual(session.grouped_answers()["m03"]["m03_q03"].value, "Другой ответ")
        self.assertTrue(completed)

    def test_invalid_answer_asks_again(self):
        session, console, _ = self.run_with(["7", "абв", "1"] + FULL_INPUT[1:] + [FINISH])
        self.assertIn("! Введите номер варианта от 1 до 3", console.text)
        self.assertEqual(session.grouped_answers()["m01"]["m01_q01"], Answer("m01_q01", 1))

    def test_no_skip_and_no_next_commands(self):
        # Пропустить вопрос или пройти дальше без ответа нельзя: «п» и «д» — не команды
        session, console, completed = self.run_with(["п", "д"] + FULL_INPUT + [FINISH])
        self.assertEqual(console.text.count("! Введите номер варианта от 1 до 3"), 2)
        self.assertNotIn("пропустить", console.text)
        self.assertTrue(completed)
        self.assertFalse(any(answer.skipped for answers in session.grouped_answers().values()
                             for answer in answers.values()))
        self.assertEqual([result.status for result in session.finish()], [Status.OK] * 3)

    def test_back_shows_previous_answer_and_requires_answer_again(self):
        session, console, _ = self.run_with(["1", "н", "3"] + FULL_INPUT[1:] + [FINISH])
        self.assertIn("Ваш прежний ответ: 1 — Не согласен — введите ответ заново", console.text)
        self.assertEqual(session.grouped_answers()["m01"]["m01_q01"].value, 3)

    def test_back_on_first_question(self):
        _, console, _ = self.run_with(["н"] + FULL_INPUT + [FINISH])
        self.assertIn("! Вы уже находитесь на первом вопросе", console.text)

    def test_empty_input_and_help(self):
        _, console, _ = self.run_with(["", "?"] + FULL_INPUT + [FINISH])
        self.assertIn("! Введите ответ или команду", console.text)
        self.assertGreaterEqual(console.text.count("Команды:"), 2)

    def test_interrupted_survey_is_not_completed(self):
        session, console, completed = self.run_with(["1", "2"])
        self.assertFalse(completed)
        self.assertIn("Опрос прерван", console.text)
        self.assertFalse(session.is_finished())

    def test_interrupted_on_end_screen(self):
        _, _, completed = self.run_with(FULL_INPUT)
        self.assertFalse(completed)


class RunTests(unittest.TestCase):
    """Полный сценарий: загрузка → опрос → отчёт → JSON-файл."""

    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.out = Path(self.temp_dir.name) / "portrait.json"

    def tearDown(self):
        self.temp_dir.cleanup()

    def run_console(self, lines, **kwargs):
        console = FakeConsole(lines)
        kwargs.setdefault("methods_folder", FIXTURES)
        kwargs.setdefault("out_path", self.out)
        code = run(input_fn=console.input, print_fn=console.print, **kwargs)
        return code, console

    def test_full_run_saves_portrait(self):
        code, console = self.run_console(FULL_INPUT + [FINISH], respondent_id="student-01")
        self.assertEqual(code, 0)
        self.assertIn("Методик: 3, вопросов: 9", console.text)
        self.assertIn("ПОРТРЕТ ЛИЧНОСТИ", console.text)
        self.assertIn("готово 3, частично 0, ошибок 0, нет данных 17", console.text)
        self.assertIn(f"Результат сохранён в файл {self.out}", console.text)

        data = json.loads(self.out.read_text(encoding="utf-8"))
        self.assertEqual(data["respondent_id"], "student-01")
        self.assertEqual(len(data["results"]), 20)
        self.assertEqual(data["summary"]["ok"], 3)

    def test_interrupted_run_saves_nothing(self):
        code, console = self.run_console(["1", "2"])
        self.assertEqual(code, 1)
        self.assertIn("Результат не сохранён", console.text)
        self.assertFalse(self.out.exists())

    def test_bad_source_stops_with_message(self):
        code, console = self.run_console([], methods_folder=Path(self.temp_dir.name) / "нет такой папки")
        self.assertEqual(code, 1)
        self.assertIn("Не удалось загрузить методики", console.text)
        self.assertFalse(self.out.exists())

    def test_empty_source_stops_with_message(self):
        code, console = self.run_console([], methods_folder=self.temp_dir.name)
        self.assertEqual(code, 1)
        self.assertIn("Нет ни одной методики", console.text)

    def test_cannot_save(self):
        code, console = self.run_console(FULL_INPUT + [FINISH],
                                         out_path=Path(self.temp_dir.name) / "нет папки" / "portrait.json")
        self.assertEqual(code, 1)
        self.assertIn("Не удалось сохранить результат", console.text)

    def test_main_with_bad_data_folder(self):
        # main() передаёт аргументы командной строки в run()
        missing = str(Path(self.temp_dir.name) / "нет такой папки")
        output = io.StringIO()
        with redirect_stdout(output):
            code = main(["--data", missing, "--out", str(self.out)])
        self.assertEqual(code, 1)
        self.assertIn("Не удалось загрузить методики", output.getvalue())

    def test_all_20_real_methods(self):
        # Полный прогон настоящих методик: на каждый вопрос — первый вариант (или текст «1»), в конце — «з»
        session = SurveySession(JsonSource().load_methods())
        console = FakeConsole([])
        console.input = lambda prompt="": FINISH if session.is_finished() else "1"
        self.assertTrue(run_survey(session, console.input, console.print))
        self.assertIn("Методика 20 из 20", console.text)
        results = session.finish()
        self.assertEqual([result.status for result in results], [Status.OK] * 20)


if __name__ == "__main__":
    unittest.main()
