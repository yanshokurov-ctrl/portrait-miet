"""Тесты консольного интерфейса (portrait/ui/console.py) и сквозного прогона.

Ввод пользователя подменяется списком строк, вывод собирается в список,
поэтому тесты не требуют настоящей консоли.
Методики — заглушки из portrait/methods/data (m01–m03, по 3 вопроса).
"""

import io
import json
import tempfile
import unittest
from contextlib import redirect_stdout
from pathlib import Path

from main import main
from portrait.core.engine import SurveySession
from portrait.core.errors import InvalidAnswerError
from portrait.core.models import Answer, Option, Question, QuestionType, Status
from portrait.sources.json_source import JsonSource
from portrait.ui.console import parse_answer, run, run_survey

# Полное прохождение заглушек: m01 (3 шкалы), m02 (выбор, число, шкала), m03 (шкала, выбор, текст)
FULL_INPUT = ["1", "2", "3", "1", "4", "3", "2", "1", "Взвешиваю за и против"]


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
    return SurveySession(JsonSource().load_methods())


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
        run_survey(session, console.input, console.print)
        return session, console

    def test_full_survey(self):
        session, console = self.run_with(FULL_INPUT)
        self.assertTrue(session.is_finished())
        results = session.finish()
        self.assertEqual([result.status for result in results], [Status.OK] * 3)
        self.assertEqual(results[0].scores[0].raw, 6)   # 1 + 2 + 3
        self.assertIn("Вопрос 1 из 9", console.text)
        self.assertIn("Вопрос 9 из 9", console.text)

    def test_method_titles_shown(self):
        _, console = self.run_with(FULL_INPUT)
        self.assertIn("=== Оценка особенностей личности ===", console.text)
        self.assertIn("=== Критическое мышление ===", console.text)

    def test_invalid_answer_asks_again(self):
        session, console = self.run_with(["7", "абв", "1"] + FULL_INPUT[1:])
        self.assertIn("! Введите номер варианта от 1 до 3", console.text)
        self.assertTrue(session.is_finished())
        self.assertEqual(session.grouped_answers()["m01"]["m01_q01"], Answer("m01_q01", 1))

    def test_skip(self):
        session, _ = self.run_with(["п"] + FULL_INPUT[1:])
        self.assertTrue(session.grouped_answers()["m01"]["m01_q01"].skipped)
        self.assertEqual(session.finish()[0].status, Status.PARTIAL)

    def test_back_shows_previous_answer_and_changes_it(self):
        session, console = self.run_with(["1", "н", "3"] + FULL_INPUT[1:])
        self.assertIn("Ваш ответ: 1 — Не согласен", console.text)
        self.assertEqual(session.grouped_answers()["m01"]["m01_q01"].value, 3)

    def test_back_then_keep_answer(self):
        session, _ = self.run_with(["2", "н", "д"] + FULL_INPUT[1:])
        self.assertEqual(session.grouped_answers()["m01"]["m01_q01"].value, 2)
        self.assertTrue(session.is_finished())

    def test_session_errors_are_shown(self):
        _, console = self.run_with(["н", "д"] + FULL_INPUT)
        self.assertIn("! Вы уже находитесь на первом вопросе", console.text)
        self.assertIn("Ответьте на вопрос", console.text)

    def test_empty_input_and_help(self):
        _, console = self.run_with(["", "?"] + FULL_INPUT)
        self.assertIn("! Введите ответ или команду", console.text)
        self.assertGreaterEqual(console.text.count("Команды:"), 2)

    def test_stop_midway(self):
        session, console = self.run_with(["1", "2", "с"])
        self.assertIn("Опрос завершён досрочно", console.text)
        self.assertFalse(session.is_finished())
        statuses = [result.status for result in session.finish()]
        self.assertEqual(statuses, [Status.PARTIAL, Status.NO_DATA, Status.NO_DATA])

    def test_end_of_input_stops_survey(self):
        session, console = self.run_with(["1"])
        self.assertIn("Опрос прерван", console.text)
        self.assertFalse(session.is_finished())


class RunTests(unittest.TestCase):
    """Полный сценарий: загрузка → опрос → отчёт → JSON-файл."""

    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.out = Path(self.temp_dir.name) / "portrait.json"

    def tearDown(self):
        self.temp_dir.cleanup()

    def test_full_run_saves_portrait(self):
        console = FakeConsole(FULL_INPUT)
        code = run(out_path=self.out, respondent_id="student-01", input_fn=console.input, print_fn=console.print)
        self.assertEqual(code, 0)
        self.assertIn("ПОРТРЕТ ЛИЧНОСТИ", console.text)
        self.assertIn("готово 3, частично 0, ошибок 0, нет данных 17", console.text)
        self.assertIn(f"Результат сохранён в файл {self.out}", console.text)

        data = json.loads(self.out.read_text(encoding="utf-8"))
        self.assertEqual(data["respondent_id"], "student-01")
        self.assertEqual(len(data["results"]), 20)
        self.assertEqual(data["summary"]["ok"], 3)

    def test_bad_source_stops_with_message(self):
        console = FakeConsole([])
        code = run(methods_folder=Path(self.temp_dir.name) / "нет такой папки", out_path=self.out,
                   input_fn=console.input, print_fn=console.print)
        self.assertEqual(code, 1)
        self.assertIn("Не удалось загрузить методики", console.text)
        self.assertFalse(self.out.exists())

    def test_empty_source_stops_with_message(self):
        console = FakeConsole([])
        code = run(methods_folder=self.temp_dir.name, out_path=self.out,
                   input_fn=console.input, print_fn=console.print)
        self.assertEqual(code, 1)
        self.assertIn("Нет ни одной методики", console.text)

    def test_cannot_save(self):
        console = FakeConsole(FULL_INPUT)
        code = run(out_path=Path(self.temp_dir.name) / "нет папки" / "portrait.json",
                   input_fn=console.input, print_fn=console.print)
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


if __name__ == "__main__":
    unittest.main()
