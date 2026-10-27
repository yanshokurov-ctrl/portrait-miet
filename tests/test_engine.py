"""Тесты движка опроса (portrait/core/engine.py).

Тесты частей разработчиков 1 и 2 пока выключены через @unittest.skip.
Реализовал метод — убери строку с @unittest.skip у своего класса тестов
и добейся, чтобы `python -m unittest` проходил.
"""

import unittest

from portrait.core.contracts import METHODS, MethodBlock
from portrait.core.engine import Progress, SurveySession
from portrait.core.errors import InvalidAnswerError, SessionError
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


# ---------------------------------------------------------------------------
# Методики-заглушки для тестов
# ---------------------------------------------------------------------------


class StubMethod(MethodBlock):
    """Методика из нескольких вопросов со шкалой 1–3; балл — сумма ответов."""

    def __init__(self, method_id: str, questions_count: int = 2):
        self.id = method_id
        self.name = METHODS[method_id]
        self.questions_count = questions_count
        self.received_answers = None  # что пришло в process() — для проверок

    def get_questions(self) -> list[Question]:
        options = [Option(1, "Нет"), Option(2, "Иногда"), Option(3, "Да")]
        return [
            Question(id=f"{self.id}_q{number:02d}", method_id=self.id, text=f"Вопрос {number}",
                     order=number, type=QuestionType.SCALE, options=options)
            for number in range(1, self.questions_count + 1)
        ]

    def process(self, answers: MethodAnswers) -> MethodResult:
        self.received_answers = answers
        values = [answer.value for answer in answers.values() if answer is not None and not answer.skipped]
        if not values:
            return MethodResult.no_data(self.id, self.name, "Нет ответов", total=len(answers))
        return MethodResult(self.id, self.name, Status.OK if len(values) == len(answers) else Status.PARTIAL,
                            scores=[ScaleScore("Сумма", sum(values))], answered=len(values), total=len(answers))


class FailingProcessMethod(StubMethod):
    """process() падает."""

    def process(self, answers):
        raise ZeroDivisionError("division by zero")


class WrongTypeMethod(StubMethod):
    """process() возвращает словарь вместо MethodResult."""

    def process(self, answers):
        return {"status": "ok"}


class ForeignResultMethod(StubMethod):
    """process() возвращает результат другой методики."""

    def process(self, answers):
        return MethodResult.no_data("m20", METHODS["m20"], "чужой результат")


class FailingQuestionsMethod(StubMethod):
    """get_questions() падает."""

    def get_questions(self):
        raise OSError("файл не найден")


class ForeignQuestionMethod(StubMethod):
    """get_questions() возвращает вопрос чужой методики."""

    def get_questions(self):
        return [Question(id="m20_q01", method_id="m20", text="Чужой", order=1, type="text")]


class FixedAnswersSession(SurveySession):
    """Сессия с заранее заданными ответами — чтобы проверять finish() без answer()/skip()."""

    def __init__(self, methods, answers_by_question: dict[str, Answer]):
        super().__init__(methods)
        self.fixed = answers_by_question

    def grouped_answers(self):
        return {
            method.id: {question.id: self.fixed.get(question.id)
                        for question in self._questions if question.method_id == method.id}
            for method in self._methods
        }


def question_ids(session: SurveySession) -> list[str]:
    return [question.id for question in session._questions]


# ---------------------------------------------------------------------------
# Основной разработчик: __init__ и finish()
# ---------------------------------------------------------------------------


class SessionSetupTests(unittest.TestCase):

    def test_methods_go_in_directory_order(self):
        session = SurveySession([StubMethod("m03", 1), StubMethod("m01", 2), StubMethod("m02", 1)])
        self.assertEqual(question_ids(session), ["m01_q01", "m01_q02", "m02_q01", "m03_q01"])

    def test_questions_sorted_by_order(self):
        class Reversed(StubMethod):
            def get_questions(self):
                return list(reversed(super().get_questions()))

        session = SurveySession([Reversed("m01", 3)])
        self.assertEqual(question_ids(session), ["m01_q01", "m01_q02", "m01_q03"])

    def test_no_methods(self):
        with self.assertRaises(SessionError):
            SurveySession([])

    def test_unknown_method(self):
        method = StubMethod("m01")
        method.id = "m99"
        with self.assertRaises(SessionError):
            SurveySession([method])

    def test_duplicate_method(self):
        with self.assertRaises(SessionError):
            SurveySession([StubMethod("m01"), StubMethod("m01")])

    def test_failing_get_questions_does_not_stop_survey(self):
        session = SurveySession([FailingQuestionsMethod("m01"), StubMethod("m02", 2)])
        self.assertEqual(question_ids(session), ["m02_q01", "m02_q02"])
        self.assertIn("m01", session._broken)
        self.assertIn("файл не найден", session._broken["m01"])

    def test_foreign_question_breaks_only_that_method(self):
        session = SurveySession([ForeignQuestionMethod("m01"), StubMethod("m02", 1)])
        self.assertEqual(question_ids(session), ["m02_q01"])
        self.assertIn("m01", session._broken)

    def test_empty_questions_break_method(self):
        session = SurveySession([StubMethod("m01", 0), StubMethod("m02", 1)])
        self.assertIn("m01", session._broken)


class FinishTests(unittest.TestCase):

    def test_all_answered(self):
        methods = [StubMethod("m01", 2), StubMethod("m02", 1)]
        answers = {"m01_q01": Answer("m01_q01", 3), "m01_q02": Answer("m01_q02", 1), "m02_q01": Answer("m02_q01", 2)}
        results = FixedAnswersSession(methods, answers).finish()
        self.assertEqual([result.method_id for result in results], ["m01", "m02"])
        self.assertEqual([result.status for result in results], [Status.OK, Status.OK])
        self.assertEqual(results[0].scores[0].raw, 4)

    def test_failing_method_gets_error_others_work(self):
        methods = [FailingProcessMethod("m01", 1), StubMethod("m02", 1)]
        answers = {"m01_q01": Answer("m01_q01", 1), "m02_q01": Answer("m02_q01", 2)}
        results = FixedAnswersSession(methods, answers).finish()
        self.assertEqual(results[0].status, Status.ERROR)
        self.assertIn("ZeroDivisionError", results[0].errors[0])
        self.assertEqual(results[0].total, 1)
        self.assertEqual(results[1].status, Status.OK)

    def test_wrong_result_type(self):
        results = FixedAnswersSession([WrongTypeMethod("m01", 1)], {}).finish()
        self.assertEqual(results[0].status, Status.ERROR)
        self.assertIn("dict", results[0].errors[0])

    def test_foreign_result(self):
        results = FixedAnswersSession([ForeignResultMethod("m01", 1)], {}).finish()
        self.assertEqual(results[0].status, Status.ERROR)
        self.assertEqual(results[0].method_id, "m01")

    def test_broken_method_gets_error(self):
        results = FixedAnswersSession([FailingQuestionsMethod("m01"), StubMethod("m02", 1)], {}).finish()
        self.assertEqual([result.method_id for result in results], ["m01", "m02"])
        self.assertEqual(results[0].status, Status.ERROR)
        self.assertEqual(results[1].status, Status.NO_DATA)

    def test_method_gets_copy_of_answers(self):
        method = StubMethod("m01", 1)
        session = FixedAnswersSession([method], {"m01_q01": Answer("m01_q01", 2)})
        session.finish()
        method.received_answers.clear()  # методика «портит» свои ответы
        self.assertEqual(session.finish()[0].status, Status.OK)


# ---------------------------------------------------------------------------
# Разработчик 1: показ вопросов и навигация
# ---------------------------------------------------------------------------


class NavigationTests(unittest.TestCase):

    def setUp(self):
        self.session = SurveySession([StubMethod("m01", 2), StubMethod("m02", 1)])

    def give_answer(self, value=1):
        """Записывает ответ на текущий вопрос напрямую, не через answer() (его делает разработчик 2)."""
        question = self.session._questions[self.session._index]
        self.session._answers[question.id] = Answer(question.id, value)

    def test_starts_with_first_question(self):
        self.assertEqual(self.session.current_question().id, "m01_q01")
        self.assertFalse(self.session.is_finished())

    def test_progress_at_start(self):
        self.assertEqual(self.session.progress(), Progress(number=1, total=3, answered=0))

    def test_next_after_answer(self):
        self.give_answer()
        self.session.next()
        self.assertEqual(self.session.current_question().id, "m01_q02")
        self.assertEqual(self.session.progress(), Progress(number=2, total=3, answered=1))

    def test_next_without_answer(self):
        with self.assertRaises(SessionError):
            self.session.next()
        self.assertEqual(self.session.current_question().id, "m01_q01")

    def test_skipped_question_allows_next_but_not_counted(self):
        self.session._answers["m01_q01"] = Answer.skip("m01_q01")
        self.session.next()
        self.assertEqual(self.session.progress().answered, 0)

    def test_back_on_first_question(self):
        with self.assertRaises(SessionError):
            self.session.back()

    def test_back_and_forward(self):
        self.give_answer()
        self.session.next()
        self.session.back()
        self.assertEqual(self.session.current_question().id, "m01_q01")
        self.session.next()
        self.assertEqual(self.session.current_question().id, "m01_q02")

    def test_goes_across_methods_and_finishes(self):
        for expected in ["m01_q01", "m01_q02", "m02_q01"]:
            self.assertEqual(self.session.current_question().id, expected)
            self.give_answer()
            self.session.next()
        self.assertTrue(self.session.is_finished())
        self.assertIsNone(self.session.current_question())
        self.assertEqual(self.session.progress(), Progress(number=3, total=3, answered=3))

    def test_next_when_finished(self):
        for _ in range(3):
            self.give_answer()
            self.session.next()
        with self.assertRaises(SessionError):
            self.session.next()

    def test_back_from_end(self):
        for _ in range(3):
            self.give_answer()
            self.session.next()
        self.session.back()
        self.assertFalse(self.session.is_finished())
        self.assertEqual(self.session.current_question().id, "m02_q01")

    def test_survey_without_questions_is_finished(self):
        session = SurveySession([FailingQuestionsMethod("m01")])
        self.assertTrue(session.is_finished())
        self.assertIsNone(session.current_question())
        self.assertEqual(session.progress(), Progress(number=0, total=0, answered=0))


# ---------------------------------------------------------------------------
# Разработчик 2: приём ответов и группировка
# ---------------------------------------------------------------------------


class AnswersTests(unittest.TestCase):

    def setUp(self):
        self.session = SurveySession([StubMethod("m01", 2), StubMethod("m02", 1)])

    def test_answer_saves_and_moves_on(self):
        self.session.answer(3)
        self.assertEqual(self.session._answers["m01_q01"], Answer("m01_q01", 3))
        self.assertEqual(self.session._index, 1)

    def test_invalid_answer(self):
        with self.assertRaises(InvalidAnswerError) as context:
            self.session.answer(7)
        self.assertIn("1", str(context.exception))  # в сообщении перечислены допустимые значения
        self.assertEqual(self.session._answers, {})
        self.assertEqual(self.session._index, 0)

    def test_skip(self):
        self.session.skip()
        self.assertEqual(self.session._answers["m01_q01"], Answer.skip("m01_q01"))
        self.assertEqual(self.session._index, 1)

    def test_answer_when_finished(self):
        for _ in range(3):
            self.session.answer(1)
        with self.assertRaises(SessionError):
            self.session.answer(1)
        with self.assertRaises(SessionError):
            self.session.skip()

    def test_answer_replaces_previous(self):
        self.session.answer(1)
        self.session._index = 0  # как будто пользователь вернулся назад
        self.session.answer(3)
        self.assertEqual(self.session._answers["m01_q01"].value, 3)
        self.assertEqual(len(self.session._answers), 1)

    def test_skip_replaces_answer(self):
        self.session.answer(1)
        self.session._index = 0
        self.session.skip()
        self.assertTrue(self.session._answers["m01_q01"].skipped)

    def test_grouped_answers(self):
        self.session.answer(3)
        self.session.skip()
        grouped = self.session.grouped_answers()
        self.assertEqual(list(grouped), ["m01", "m02"])
        self.assertEqual(grouped["m01"], {"m01_q01": Answer("m01_q01", 3), "m01_q02": Answer.skip("m01_q02")})
        self.assertEqual(grouped["m02"], {"m02_q01": None})  # до вопроса не дошли

    def test_grouped_answers_with_broken_method(self):
        session = SurveySession([FailingQuestionsMethod("m01"), StubMethod("m02", 1)])
        self.assertEqual(session.grouped_answers(), {"m01": {}, "m02": {"m02_q01": None}})

    def test_full_survey_then_finish(self):
        self.session.answer(3)
        self.session.answer(2)
        self.session.skip()
        results = self.session.finish()
        self.assertEqual([result.status for result in results], [Status.OK, Status.NO_DATA])
        self.assertEqual(results[0].scores[0].raw, 5)

    def test_stop_midway_then_finish(self):
        self.session.answer(3)
        results = self.session.finish()
        self.assertEqual([result.status for result in results], [Status.PARTIAL, Status.NO_DATA])


if __name__ == "__main__":
    unittest.main()
