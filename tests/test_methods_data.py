"""Проверка 20 настоящих методик (portrait/methods/data).

Для каждой методики подаются заранее известные ответы, и баллы сверяются
с тем, что получается по ключам и диапазонам из исходных документов методик.
Так проверяется, что вопросы и ключи перенесены без ошибок.
"""

import unittest

from portrait.core.contracts import METHODS
from portrait.core.models import Answer, QuestionType, Status
from portrait.sources.json_source import JsonSource

# Сколько вопросов в каждой методике по исходным документам
QUESTION_COUNTS = {
    "m01": 30, "m02": 16, "m03": 10, "m04": 10, "m05": 24, "m06": 30, "m07": 23, "m08": 32, "m09": 57,
    "m10": 75, "m11": 12, "m12": 34, "m13": 20, "m14": 10, "m15": 23, "m16": 18, "m17": 26, "m18": 21,
    "m19": 20, "m20": 8,
}

METHODS_BY_ID = {method.id: method for method in JsonSource().load_methods()}


def run_method(method_id, value_for):
    """Отвечает на все вопросы методики: value_for(номер вопроса, вопрос) → значение ответа.

    Возвращает (результат, {шкала: балл}).
    """
    method = METHODS_BY_ID[method_id]
    answers = {question.id: Answer(question.id, value_for(question.order, question))
               for question in method.get_questions()}
    result = method.process(answers)
    return result, {score.scale: score.raw for score in result.scores}


def everywhere(value):
    return lambda number, question: value


def by_reverse(direct_value, reverse_value, reverse_items):
    return lambda number, question: reverse_value if number in reverse_items else direct_value


class AllMethodsTests(unittest.TestCase):

    def test_all_20_methods_in_order(self):
        self.assertEqual(list(METHODS_BY_ID), list(METHODS))

    def test_question_counts(self):
        counts = {method_id: len(method.get_questions()) for method_id, method in METHODS_BY_ID.items()}
        self.assertEqual(counts, QUESTION_COUNTS)

    def test_every_method_has_instruction(self):
        for method_id, method in METHODS_BY_ID.items():
            with self.subTest(method_id=method_id):
                self.assertGreater(len(method.instruction), 20)

    def test_no_method_names_in_test_text(self):
        # ТЗ: текст теста — без названий методик (и без авторов)
        for method_id, method in METHODS_BY_ID.items():
            texts = [method.instruction] + [question.text for question in method.get_questions()]
            texts += [option.label for question in method.get_questions() for option in question.options]
            joined = " ".join(texts).lower()
            with self.subTest(method_id=method_id):
                self.assertNotIn("методика", joined)
                for name in METHODS.values():
                    self.assertNotIn(name.lower(), joined)

    def test_answering_first_option_everywhere_gives_full_result(self):
        for method_id, method in METHODS_BY_ID.items():
            with self.subTest(method_id=method_id):
                result, _ = run_method(method_id, lambda n, q: q.options[0].value if q.options else "ответ")
                self.assertEqual(result.status, Status.OK)
                self.assertEqual(result.answered, QUESTION_COUNTS[method_id])

    def test_scales_with_pairs_cover_all_items_once(self):
        # В этих методиках каждый пункт входит ровно в одну шкалу
        for method_id in ("m05", "m06", "m12", "m18", "m19"):
            items = [item for scale in METHODS_BY_ID[method_id].scoring["scales"] for item in scale["items"]]
            with self.subTest(method_id=method_id):
                self.assertEqual(sorted(items), list(range(1, QUESTION_COUNTS[method_id] + 1)))


class MethodKeysTests(unittest.TestCase):
    """Баллы по известным ответам — сверка с ключами из документов."""

    def test_m01_moral_scales(self):
        _, scores = run_method("m01", everywhere("нет"))
        self.assertEqual(list(scores.values()), [4, 5, 5, 5, 5, 0])
        _, scores = run_method("m01", everywhere("да"))
        self.assertEqual(list(scores.values()), [1, 0, 0, 0, 0, 5])

    def test_m02_reverse_items(self):
        _, scores = run_method("m02", everywhere(5))
        self.assertEqual(scores, {"Самооценка": 8, "Самоэффективность": 20, "Целостность": 20, "Уникальность": 16})
        _, scores = run_method("m02", everywhere(1))
        self.assertEqual(scores, {"Самооценка": 16, "Самоэффективность": 4, "Целостность": 4, "Уникальность": 8})

    def test_m03_ranges(self):
        _, scores = run_method("m03", everywhere(1))
        self.assertEqual(list(scores.values()), [10, 2, 4, 4])
        _, scores = run_method("m03", everywhere(4))
        self.assertEqual(list(scores.values()), [40, 8, 16, 16])

    def test_m04_key_matches_expanded_key(self):
        correct = {1: "6 перекладин", 2: "12 марок", 3: "1 стог", 4: "вторым", 5: "72 метра", 6: "4 дня",
                   7: "1 кг", 8: "3 носка", 9: "1 час", 10: "11 месяцев"}
        intuitive = {1: "3 перекладины", 2: "6 марок", 3: "9 стогов", 4: "первым", 5: "75 метр", 6: "5 дней",
                     7: "0,5 кг", 8: "невозможно определить", 9: "13 часов", 10: "4 месяца"}

        def pick(expected):
            return lambda n, q: next(o.value for o in q.options if o.label.startswith(expected[n]))

        _, scores = run_method("m04", pick(correct))
        self.assertEqual(list(scores.values()), [10, 0])
        _, scores = run_method("m04", pick(intuitive))
        self.assertEqual(list(scores.values()), [0, 10])

    def test_m05_pairs(self):
        _, scores = run_method("m05", everywhere(5))
        self.assertEqual(set(scores.values()), {10})
        self.assertEqual(len(scores), 12)

    def test_m06_pairs(self):
        _, scores = run_method("m06", everywhere(4))
        self.assertEqual(set(scores.values()), {8})
        self.assertEqual(len(scores), 15)

    def test_m07_altruism(self):
        reverse = {3, 5, 7, 9, 11, 15, 17, 19, 21}
        _, scores = run_method("m07", by_reverse(6, 0, reverse))  # «абсолютно верно» на прямые, «категорически не верно» на обратные
        self.assertEqual(scores, {"Шкала лжи": 30, "Уровень альтруизма": 108})
        _, scores = run_method("m07", by_reverse(0, 6, reverse))
        self.assertEqual(scores, {"Шкала лжи": 0, "Уровень альтруизма": 0})

    def test_m08_metacognition(self):
        _, scores = run_method("m08", everywhere(5))
        self.assertEqual(list(scores.values()), [60, 100, 25, 15, 20, 20, 10, 30, 20, 20])

    def test_m09_self_attitude(self):
        _, scores = run_method("m09", everywhere("верно"))
        self.assertEqual(list(scores.values()), [11, 5, 5, 6, 2, 8, 3, 1])
        _, scores = run_method("m09", everywhere("неверно"))
        self.assertEqual(list(scores.values()), [17, 3, 3, 1, 5, 0, 4, 6])

    def test_m10_max_30_per_scale(self):
        _, scores = run_method("m10", everywhere(2))
        self.assertEqual(set(scores.values()), {30})
        _, scores = run_method("m10", everywhere(0))
        self.assertEqual(set(scores.values()), {0})

    def test_m11_antisocial_creativity(self):
        _, scores = run_method("m11", everywhere(4))
        self.assertEqual(list(scores.values()), [24, 16, 12, 48])

    def test_m12_means(self):
        _, scores = run_method("m12", lambda n, q: 5 if n == 7 else 1)
        self.assertEqual(scores["Коммуникативные мотивы"], 2.0)  # (5 + 1 + 1 + 1) / 4
        self.assertEqual(scores["Мотивы избегания"], 1.0)

    def test_m13_meaning_of_life(self):
        descending = {2, 5, 6, 7, 10, 13, 14, 15, 18, 19, 20}
        _, scores = run_method("m13", by_reverse(7, 1, descending))  # везде полюс «есть цель»
        self.assertEqual(list(scores.values()), [140, 42, 42, 35, 28, 42])
        _, scores = run_method("m13", by_reverse(1, 7, descending))
        self.assertEqual(list(scores.values()), [20, 6, 6, 5, 4, 6])

    def test_m14_communication_styles(self):
        result, scores = run_method("m14", lambda n, q: q.options[0].value)
        self.assertEqual(list(scores.values()), [5, 3, 2, 0])
        self.assertIn("Действие", result.interpretation)
        result, scores = run_method("m14", lambda n, q: q.options[1].value)
        self.assertEqual(list(scores.values()), [0, 2, 3, 5])
        self.assertIn("Идеи", result.interpretation)

    def test_m15_closed_answers(self):
        key = {1: "нет", 3: "да", 4: "нет", 6: "нет", 8: "нет", 10: "Вова", 11: "Коля", 12: "Сергей"}
        result, scores = run_method("m15", lambda n, q: key.get(n, q.options[0].value if q.options else "ответ"))
        self.assertEqual(list(scores.values()), [8])
        self.assertIn("эксперт", result.interpretation)

    def test_m16_need_for_cognition(self):
        reverse = {3, 4, 5, 7, 8, 9, 12, 16, 17}
        _, scores = run_method("m16", by_reverse(7, 1, reverse))
        self.assertEqual(scores, {"Потребность в познании": 126})
        _, scores = run_method("m16", everywhere(7))
        self.assertEqual(scores, {"Потребность в познании": 72})

    def test_m17_indices(self):
        _, scores = run_method("m17", everywhere(5))
        self.assertEqual(list(scores.values())[:13], [10] * 13)
        self.assertEqual(list(scores.values())[13:], [30, 30, 30, 90, 30, 60])
        # минимум индекса адаптивности по документу: −12
        emotional = {10, 23, 11, 24, 12, 25}
        _, scores = run_method("m17", lambda n, q: 5 if n in emotional else 1)
        self.assertEqual(scores["Индекс общей адаптивности (ИОАД)"], -12)

    def test_m18_three_scales(self):
        _, scores = run_method("m18", everywhere(5))
        self.assertEqual(list(scores.values()), [35, 35, 35])

    def test_m19_accentuations(self):
        _, scores = run_method("m19", everywhere(5))
        self.assertEqual(set(scores.values()), {10})
        self.assertEqual(len(scores), 10)

    def test_m20_emotional_intelligence(self):
        _, scores = run_method("m20", everywhere(4))
        self.assertEqual(list(scores.values()), [5, 5, 8, 2, 10, 10, 20])
        _, scores = run_method("m20", by_reverse(4, 1, {2, 4, 5, 6}))
        self.assertEqual(scores["Общий показатель ЭИ (ОЭИ)"], 32)


if __name__ == "__main__":
    unittest.main()
