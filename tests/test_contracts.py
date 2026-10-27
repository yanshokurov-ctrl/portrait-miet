"""Тесты контракта методики (portrait/core/contracts.py).

DemoMethod — пример методики, которая выполняет контракт.
Его можно брать за образец при написании своих методик.
"""

import unittest

from portrait.core.contracts import MIN_ANSWERED_SHARE, METHODS, MethodBlock, method_name, result_status
from portrait.core.models import (
    Answer,
    MethodAnswers,
    MethodResult,
    Option,
    Question,
    QuestionType,
    ScaleScore,
    Status,
)


class DemoMethod(MethodBlock):
    """Учебная методика из трёх вопросов: балл — сумма ответов по шкале 1–3."""

    id = "m16"
    name = METHODS["m16"]

    def get_questions(self) -> list[Question]:
        texts = [
            "Мне нравится разбираться в сложных задачах",
            "Я с удовольствием читаю о новом",
            "Мне интересно, как устроены вещи",
        ]
        options = [Option(1, "Не согласен"), Option(2, "Затрудняюсь"), Option(3, "Согласен")]
        return [
            Question(id=f"{self.id}_q{number:02d}", method_id=self.id, text=text,
                     order=number, type=QuestionType.SCALE, options=options)
            for number, text in enumerate(texts, start=1)
        ]

    def process(self, answers: MethodAnswers) -> MethodResult:
        total = len(answers)
        values = [answer.value for answer in answers.values()
                  if answer is not None and not answer.skipped]

        if not values:
            return MethodResult.no_data(self.id, self.name, "Нет ни одного ответа", total=total)

        raw = sum(values)
        level = "высокий" if raw >= 7 else "средний" if raw >= 5 else "низкий"
        return MethodResult(
            method_id=self.id,
            method_name=self.name,
            status=Status.OK if len(values) == total else Status.PARTIAL,
            scores=[ScaleScore("Потребность в познании", raw, level)],
            interpretation=f"Уровень потребности в познании: {level}",
            answered=len(values),
            total=total,
        )


class MethodsDirectoryTests(unittest.TestCase):

    def test_there_are_20_methods(self):
        self.assertEqual(len(METHODS), 20)

    def test_ids_go_in_order(self):
        self.assertEqual(list(METHODS), [f"m{number:02d}" for number in range(1, 21)])

    def test_names_are_not_empty_and_unique(self):
        names = list(METHODS.values())
        self.assertTrue(all(name.strip() for name in names))
        self.assertEqual(len(names), len(set(names)))

    def test_method_name(self):
        self.assertEqual(method_name("m20"), "Эмоциональный интеллект")

    def test_unknown_method_name(self):
        with self.assertRaises(KeyError):
            method_name("m99")


class MethodBlockTests(unittest.TestCase):

    def setUp(self):
        self.method = DemoMethod()
        self.question_ids = [question.id for question in self.method.get_questions()]

    def test_base_class_cannot_be_created(self):
        with self.assertRaises(TypeError):
            MethodBlock()

    def test_method_is_in_directory(self):
        self.assertEqual(METHODS[self.method.id], self.method.name)

    def test_questions_follow_contract(self):
        questions = self.method.get_questions()
        self.assertTrue(all(question.method_id == self.method.id for question in questions))
        self.assertEqual(len(self.question_ids), len(set(self.question_ids)))
        self.assertEqual([question.order for question in questions], [1, 2, 3])

    def test_all_answered(self):
        answers = {question_id: Answer(question_id, 3) for question_id in self.question_ids}
        result = self.method.process(answers)
        self.assertEqual(result.status, Status.OK)
        self.assertEqual(result.scores[0].raw, 9)
        self.assertEqual((result.answered, result.total), (3, 3))

    def test_some_skipped(self):
        answers = {question_id: Answer(question_id, 2) for question_id in self.question_ids}
        answers[self.question_ids[0]] = Answer.skip(self.question_ids[0])
        result = self.method.process(answers)
        self.assertEqual(result.status, Status.PARTIAL)
        self.assertEqual((result.answered, result.total), (2, 3))

    def test_nothing_answered(self):
        answers = {question_id: None for question_id in self.question_ids}
        result = self.method.process(answers)
        self.assertEqual(result.status, Status.NO_DATA)
        self.assertEqual(result.method_id, self.method.id)

    def test_process_does_not_keep_state(self):
        answers = {question_id: Answer(question_id, 1) for question_id in self.question_ids}
        self.assertEqual(self.method.process(answers), self.method.process(answers))


class ResultStatusTests(unittest.TestCase):
    """Общее правило статуса по доле ответов (MIN_ANSWERED_SHARE = 0.5)."""

    def test_all_answered(self):
        self.assertEqual(result_status(10, 10), Status.OK)

    def test_half_answered_is_partial(self):
        self.assertEqual(result_status(5, 10), Status.PARTIAL)
        self.assertEqual(result_status(9, 10), Status.PARTIAL)

    def test_less_than_half_is_no_data(self):
        self.assertEqual(result_status(4, 10), Status.NO_DATA)
        self.assertEqual(result_status(1, 3), Status.NO_DATA)

    def test_nothing_answered(self):
        self.assertEqual(result_status(0, 10), Status.NO_DATA)
        self.assertEqual(result_status(0, 0), Status.NO_DATA)

    def test_share_constant(self):
        self.assertEqual(MIN_ANSWERED_SHARE, 0.5)


if __name__ == "__main__":
    unittest.main()
