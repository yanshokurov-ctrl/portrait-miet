"""Тесты загрузки методик из JSON (portrait/sources/json_source.py, portrait/methods/json_method.py)."""

import json
import tempfile
import unittest
from pathlib import Path

from portrait.core.contracts import METHODS, MethodBlock
from portrait.core.errors import SourceError
from portrait.core.models import Answer, QuestionType, Status
from portrait.methods.json_method import JsonMethod, points_word
from portrait.sources.base import QuestionSource
from portrait.sources.json_source import JsonSource

SCALE_OPTIONS = [{"value": 1, "label": "Нет"}, {"value": 2, "label": "Иногда"}, {"value": 3, "label": "Да"}]

# Небольшие тестовые методики (m01–m03, по 3 вопроса) — чтобы тесты не зависели от настоящих данных
FIXTURES = Path(__file__).parent / "fixtures" / "methods"


def make_method_data(method_id: str = "m05", questions_count: int = 3) -> dict:
    """Словарь методики со шкальными вопросами для тестов."""
    return {
        "method_id": method_id,
        "questions": [
            {"text": f"Вопрос {number}", "type": "scale", "options": SCALE_OPTIONS}
            for number in range(1, questions_count + 1)
        ],
    }


class JsonSourceStubsTests(unittest.TestCase):
    """Загрузка тестовых методик из tests/fixtures/methods."""

    def setUp(self):
        self.methods = JsonSource(FIXTURES).load_methods()

    def test_instruction_loaded(self):
        self.assertEqual(self.methods[0].instruction, "Тестовая инструкция первой методики.")

    def test_source_follows_contract(self):
        self.assertIsInstance(JsonSource(), QuestionSource)
        self.assertTrue(all(isinstance(method, MethodBlock) for method in self.methods))

    def test_three_stubs_in_directory_order(self):
        self.assertEqual([method.id for method in self.methods], ["m01", "m02", "m03"])

    def test_names_from_directory(self):
        for method in self.methods:
            self.assertEqual(method.name, METHODS[method.id])

    def test_questions_get_ids_and_order(self):
        for method in self.methods:
            questions = method.get_questions()
            self.assertGreaterEqual(len(questions), 3)
            self.assertEqual([question.id for question in questions],
                             [f"{method.id}_q{number:02d}" for number in range(1, len(questions) + 1)])
            self.assertEqual([question.order for question in questions], list(range(1, len(questions) + 1)))
            self.assertTrue(all(question.method_id == method.id for question in questions))

    def test_stubs_use_different_question_types(self):
        types = {question.type for method in self.methods for question in method.get_questions()}
        self.assertTrue({QuestionType.SCALE, QuestionType.CHOICE, QuestionType.NUMBER} <= types)


class JsonMethodProcessTests(unittest.TestCase):
    """Временный подсчёт: сумма числовых ответов."""

    def setUp(self):
        self.method = JsonMethod(make_method_data())
        self.ids = [question.id for question in self.method.get_questions()]

    def test_all_answered(self):
        result = self.method.process({qid: Answer(qid, 3) for qid in self.ids})
        self.assertEqual(result.status, Status.OK)
        self.assertEqual(result.scores[0].raw, 9)
        self.assertEqual((result.answered, result.total), (3, 3))

    def test_skipped_question_gives_partial(self):
        answers = {qid: Answer(qid, 2) for qid in self.ids}
        answers[self.ids[0]] = Answer.skip(self.ids[0])
        result = self.method.process(answers)
        self.assertEqual(result.status, Status.PARTIAL)
        self.assertEqual(result.scores[0].raw, 4)
        self.assertEqual((result.answered, result.total), (2, 3))

    def test_stopped_midway_gives_partial(self):
        answers = {qid: None for qid in self.ids}
        answers[self.ids[0]] = Answer(self.ids[0], 1)
        answers[self.ids[1]] = Answer(self.ids[1], 2)
        result = self.method.process(answers)
        self.assertEqual(result.status, Status.PARTIAL)
        self.assertEqual(result.answered, 2)

    def test_too_few_answers_gives_no_data(self):
        # 1 из 3 — меньше MIN_ANSWERED_SHARE (50%)
        answers = {qid: None for qid in self.ids}
        answers[self.ids[0]] = Answer(self.ids[0], 1)
        result = self.method.process(answers)
        self.assertEqual(result.status, Status.NO_DATA)
        self.assertIn("1 из 3", result.errors[0])

    def test_all_skipped_gives_no_data(self):
        result = self.method.process({qid: Answer.skip(qid) for qid in self.ids})
        self.assertEqual(result.status, Status.NO_DATA)
        self.assertEqual(result.answered, 0)

    def test_nothing_answered_gives_no_data(self):
        result = self.method.process({qid: None for qid in self.ids})
        self.assertEqual(result.status, Status.NO_DATA)

    def test_text_answers_are_not_summed(self):
        method = JsonMethod({"method_id": "m05", "questions": [
            {"text": "Число", "type": "number"},
            {"text": "Текст", "type": "text"},
        ]})
        result = method.process({"m05_q01": Answer("m05_q01", 2.5), "m05_q02": Answer("m05_q02", "ответ")})
        self.assertEqual(result.status, Status.OK)
        self.assertEqual(result.scores[0].raw, 2.5)

    def test_points_word(self):
        cases = {0: "баллов", 1: "балл", 2: "балла", 4: "балла", 5: "баллов", 11: "баллов",
                 12: "баллов", 21: "балл", 22: "балла", 111: "баллов", 2.5: "балла", 6.0: "баллов"}
        for number, word in cases.items():
            with self.subTest(number=number):
                self.assertEqual(points_word(number), word)

    def test_get_questions_returns_copy(self):
        self.method.get_questions().clear()
        self.assertEqual(len(self.method.get_questions()), 3)


class JsonSourceErrorTests(unittest.TestCase):
    """Ошибки в файлах: понятное сообщение с именем файла."""

    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.folder = Path(self.temp_dir.name)

    def tearDown(self):
        self.temp_dir.cleanup()

    def write(self, name: str, content) -> None:
        text = content if isinstance(content, str) else json.dumps(content, ensure_ascii=False)
        (self.folder / name).write_text(text, encoding="utf-8")

    def assert_load_error(self, file_name: str, message_part: str) -> None:
        with self.assertRaises(SourceError) as context:
            JsonSource(self.folder).load_methods()
        self.assertIn(file_name, str(context.exception))
        self.assertIn(message_part, str(context.exception))

    def test_order_follows_directory_not_file_names(self):
        self.write("b.json", make_method_data("m01"))
        self.write("a.json", make_method_data("m20"))
        self.write("c.json", make_method_data("m07"))
        ids = [method.id for method in JsonSource(self.folder).load_methods()]
        self.assertEqual(ids, ["m01", "m07", "m20"])

    def test_empty_folder_gives_empty_list(self):
        self.assertEqual(JsonSource(self.folder).load_methods(), [])

    def test_missing_folder(self):
        with self.assertRaises(SourceError):
            JsonSource(self.folder / "нет такой папки").load_methods()

    def test_broken_json(self):
        self.write("m01.json", '{"method_id": "m01", ')
        self.assert_load_error("m01.json", "Ошибка при чтении")

    def test_not_an_object(self):
        self.write("m01.json", "[1, 2, 3]")
        self.assert_load_error("m01.json", "объект")

    def test_empty_object(self):
        self.write("m03.json", "{}")
        self.assert_load_error("m03.json", "method_id")

    def test_no_questions(self):
        self.write("m02.json", {"method_id": "m02"})
        self.assert_load_error("m02.json", "questions")

    def test_unknown_method_id(self):
        self.write("m99.json", make_method_data("m99"))
        self.assert_load_error("m99.json", "m99")

    def test_question_without_text(self):
        self.write("m01.json", {"method_id": "m01", "questions": [{"type": "number"}]})
        self.assert_load_error("m01.json", "text")

    def test_option_without_label(self):
        self.write("m02.json", {"method_id": "m02", "questions": [
            {"text": "Да или нет?", "type": "choice", "options": [{"value": "да"}, {"value": "нет"}]},
        ]})
        self.assert_load_error("m02.json", "label")

    def test_choice_without_options(self):
        self.write("m01.json", {"method_id": "m01", "questions": [{"text": "Вопрос", "type": "choice"}]})
        self.assert_load_error("m01.json", "варианты ответа")

    def test_duplicate_method(self):
        self.write("first.json", make_method_data("m01"))
        self.write("second.json", make_method_data("m01"))
        self.assert_load_error("second.json", "уже загружена")


if __name__ == "__main__":
    unittest.main()
