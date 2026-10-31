"""Тесты подсчёта баллов по ключам (portrait/methods/scoring.py)."""

import unittest

from portrait.core.models import Option, Question, QuestionType
from portrait.methods.scoring import compute_scores, interpret, points_word, validate_scoring


def scale_question(number: int) -> Question:
    return Question(f"m01_q{number:02d}", "m01", f"Вопрос {number}", number, QuestionType.SCALE,
                    [Option(1, "Нет"), Option(2, "Иногда"), Option(3, "Да")])


def choice_question(number: int) -> Question:
    return Question(f"m01_q{number:02d}", "m01", f"Вопрос {number}", number, QuestionType.CHOICE,
                    [Option("да", "Да"), Option("нет", "Нет")])


QUESTIONS = [scale_question(1), scale_question(2), scale_question(3), choice_question(4), choice_question(5)]


def scores_dict(scoring, values):
    return {score.scale: score.raw for score in compute_scores(scoring, values)}


class ValidateScoringTests(unittest.TestCase):

    def assert_invalid(self, scoring, message_part):
        with self.assertRaises(ValueError) as context:
            validate_scoring(scoring, QUESTIONS)
        self.assertIn(message_part, str(context.exception))

    def test_valid(self):
        validate_scoring({"reverse_base": 4, "scales": [
            {"name": "А", "items": [1, 2, 3], "reverse": [2]},
            {"name": "Б", "key": {"4": "да", "5": "нет"}},
            {"name": "В", "plus": ["А", "Б"], "minus": []},
        ]}, QUESTIONS)

    def test_no_scales(self):
        self.assert_invalid({}, "scales")

    def test_scale_without_name(self):
        self.assert_invalid({"scales": [{"items": [1]}]}, "name")

    def test_duplicate_name(self):
        self.assert_invalid({"scales": [{"name": "А", "items": [1]}, {"name": "А", "items": [2]}]}, "повторяется")

    def test_two_kinds_in_one_scale(self):
        self.assert_invalid({"scales": [{"name": "А", "items": [1], "key": {"4": "да"}}]}, "ровно одно")

    def test_item_out_of_range(self):
        self.assert_invalid({"scales": [{"name": "А", "items": [1, 9]}]}, "№9")

    def test_repeated_item(self):
        self.assert_invalid({"scales": [{"name": "А", "items": [1, 1]}]}, "повторяются")

    def test_reverse_not_in_items(self):
        self.assert_invalid({"reverse_base": 4, "scales": [{"name": "А", "items": [1], "reverse": [2]}]},
                            "обратные")

    def test_reverse_without_base(self):
        self.assert_invalid({"scales": [{"name": "А", "items": [1, 2], "reverse": [2]}]}, "reverse_base")

    def test_sum_of_text_answers(self):
        self.assert_invalid({"scales": [{"name": "А", "items": [4]}]}, "числами")

    def test_unknown_aggregate(self):
        self.assert_invalid({"scales": [{"name": "А", "items": [1], "aggregate": "median"}]}, "aggregate")

    def test_key_value_not_in_options(self):
        self.assert_invalid({"scales": [{"name": "А", "key": {"4": "может быть"}}]}, "может быть")

    def test_composite_of_unknown_scale(self):
        self.assert_invalid({"scales": [{"name": "А", "plus": ["Б"]}]}, "«Б»")

    def test_composite_must_refer_to_earlier_scale(self):
        self.assert_invalid({"scales": [{"name": "В", "plus": ["А"]}, {"name": "А", "items": [1]}]}, "«А»")

    def test_unknown_interpretation(self):
        self.assert_invalid({"scales": [{"name": "А", "items": [1]}], "interpretation": {"type": "magic"}},
                            "интерпретации")


class ComputeScoresTests(unittest.TestCase):

    def test_sum_with_reverse(self):
        scoring = {"reverse_base": 4, "scales": [{"name": "А", "items": [1, 2, 3], "reverse": [2]}]}
        # 3 + (4 − 3) + 1 = 5
        self.assertEqual(scores_dict(scoring, {1: 3, 2: 3, 3: 1}), {"А": 5})

    def test_missing_answers_not_counted(self):
        scoring = {"scales": [{"name": "А", "items": [1, 2, 3]}]}
        self.assertEqual(scores_dict(scoring, {1: 3}), {"А": 3})

    def test_mean(self):
        scoring = {"scales": [{"name": "А", "items": [1, 2, 3], "aggregate": "mean"}]}
        self.assertEqual(scores_dict(scoring, {1: 1, 2: 2, 3: 2}), {"А": 1.67})
        self.assertEqual(scores_dict(scoring, {}), {"А": 0})

    def test_key(self):
        scoring = {"scales": [{"name": "А", "key": {"4": "да", "5": "нет"}}]}
        self.assertEqual(scores_dict(scoring, {4: "да", 5: "да"}), {"А": 1})
        self.assertEqual(scores_dict(scoring, {}), {"А": 0})

    def test_composite_plus_minus(self):
        scoring = {"scales": [
            {"name": "А", "items": [1, 2]},
            {"name": "Б", "items": [3]},
            {"name": "А+Б", "plus": ["А", "Б"]},
            {"name": "А−Б", "plus": ["А"], "minus": ["Б"]},
        ]}
        self.assertEqual(scores_dict(scoring, {1: 3, 2: 3, 3: 2}), {"А": 6, "Б": 2, "А+Б": 8, "А−Б": 4})


class InterpretTests(unittest.TestCase):
    SCALES = ["А", "Б", "В"]

    def text(self, raws, minimum=4):
        scoring = {"interpretation": {"type": "dominant", "scales": self.SCALES, "min": minimum,
                                      "title": "Стиль"}}
        scores = compute_scores({"scales": [{"name": name, "items": [1]} for name in self.SCALES]}, {})
        for score, raw in zip(scores, raws):
            score.raw = raw
        return interpret(scoring, scores)

    def test_single_leader(self):
        self.assertEqual(self.text([5, 3, 2]), "Стиль: А (5 баллов).")

    def test_tie(self):
        self.assertEqual(self.text([3, 3, 2]), "Стиль: совмещаются А, Б (по 3 балла).")

    def test_below_minimum(self):
        self.assertIn("не выражен", self.text([3, 2, 1]))

    def test_note_added(self):
        self.assertEqual(interpret({"note": "Пояснение."}, []), "Пояснение.")

    def test_points_word(self):
        self.assertEqual([points_word(n) for n in (1, 3, 5, 21)], ["балл", "балла", "баллов", "балл"])


if __name__ == "__main__":
    unittest.main()
