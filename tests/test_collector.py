"""Тесты сборщика результатов (portrait/core/collector.py)."""

import unittest

from portrait.core.collector import collect, to_text, validate_result
from portrait.core.contracts import METHODS
from portrait.core.errors import InvalidResultError
from portrait.core.models import MethodResult, Portrait, ScaleScore, Status


def ok_result(method_id: str, raw: int = 10) -> MethodResult:
    return MethodResult(method_id, METHODS[method_id], Status.OK,
                        scores=[ScaleScore("Сумма баллов", raw, "средний")],
                        interpretation=f"Вы набрали {raw} баллов", answered=3, total=3)


class CollectTests(unittest.TestCase):

    def test_always_20_methods_in_directory_order(self):
        portrait = collect([ok_result("m03"), ok_result("m01")])
        self.assertEqual([result.method_id for result in portrait.results], list(METHODS))

    def test_given_results_are_kept(self):
        first, third = ok_result("m01", 5), ok_result("m03", 7)
        portrait = collect([third, first])
        self.assertIs(portrait.get("m01"), first)
        self.assertIs(portrait.get("m03"), third)
        self.assertEqual(portrait.warnings, [])

    def test_missing_methods_get_no_data(self):
        portrait = collect([ok_result("m01")])
        missing = portrait.get("m20")
        self.assertEqual(missing.status, Status.NO_DATA)
        self.assertEqual(missing.method_name, METHODS["m20"])
        self.assertIn("не получен", missing.errors[0])

    def test_empty_input(self):
        portrait = collect([])
        self.assertEqual(portrait.summary(), {"ok": 0, "partial": 0, "error": 0, "no_data": 20})

    def test_summary(self):
        results = [
            ok_result("m01"),
            MethodResult("m02", METHODS["m02"], Status.PARTIAL, scores=[ScaleScore("Сумма баллов", 3)],
                         answered=2, total=3),
            MethodResult.error("m03", METHODS["m03"], "Сбой"),
        ]
        self.assertEqual(collect(results).summary(), {"ok": 1, "partial": 1, "error": 1, "no_data": 17})

    def test_duplicate_keeps_first(self):
        first, second = ok_result("m01", 5), ok_result("m01", 9)
        portrait = collect([first, second])
        self.assertIs(portrait.get("m01"), first)
        self.assertEqual(len(portrait.results), 20)
        self.assertTrue(any("повторный" in warning for warning in portrait.warnings))

    def test_unknown_method_rejected(self):
        unknown = MethodResult.no_data("m99", "Неизвестная", "—")
        portrait = collect([unknown])
        self.assertIsNone(portrait.get("m99"))
        self.assertTrue(any("m99" in warning for warning in portrait.warnings))

    def test_garbage_without_method_rejected(self):
        portrait = collect([42, "текст", None])
        self.assertEqual(len(portrait.warnings), 3)
        self.assertEqual(portrait.summary()["no_data"], 20)

    def test_dict_instead_of_result_gives_error(self):
        portrait = collect([{"method_id": "m02", "status": "ok"}])
        self.assertEqual(portrait.get("m02").status, Status.ERROR)
        self.assertIn("dict", portrait.get("m02").errors[0])
        self.assertTrue(any("m02" in warning for warning in portrait.warnings))

    def test_spoiled_result_gives_error(self):
        result = ok_result("m01")
        result.scores = [{"scale": "Сумма", "raw": 5}]  # испорчено после создания
        portrait = collect([result])
        self.assertEqual(portrait.get("m01").status, Status.ERROR)

    def test_wrong_name_replaced_from_directory(self):
        result = MethodResult("m01", "Старое название", Status.OK, scores=[ScaleScore("Сумма", 1)],
                              answered=1, total=1)
        portrait = collect([result])
        self.assertEqual(portrait.get("m01").method_name, METHODS["m01"])
        self.assertEqual(result.method_name, "Старое название")  # входной объект не изменён
        self.assertEqual(len(portrait.warnings), 1)

    def test_respondent_id(self):
        self.assertEqual(collect([], "student-01").respondent_id, "student-01")
        generated = collect([]).respondent_id
        self.assertTrue(generated.startswith("anon-"))
        self.assertNotEqual(generated, collect([]).respondent_id)

    def test_json_round_trip(self):
        portrait = collect([ok_result("m01"), {"method_id": "m02"}])
        self.assertEqual(Portrait.from_json(portrait.to_json()), portrait)


class ValidateResultTests(unittest.TestCase):

    def test_valid_result(self):
        validate_result(ok_result("m01"))  # не выбрасывает исключение

    def test_not_a_result(self):
        with self.assertRaises(InvalidResultError):
            validate_result({"method_id": "m01"})

    def test_answered_more_than_total(self):
        result = ok_result("m01")
        result.answered = 5
        with self.assertRaises(InvalidResultError) as context:
            validate_result(result)
        self.assertIn("больше", str(context.exception))

    def test_status_string_instead_of_enum(self):
        result = ok_result("m01")
        result.status = "отлично"
        with self.assertRaises(InvalidResultError):
            validate_result(result)

    def test_ok_without_scores(self):
        result = ok_result("m01")
        result.scores = []
        with self.assertRaises(InvalidResultError):
            validate_result(result)


class ToTextTests(unittest.TestCase):

    def setUp(self):
        results = [
            ok_result("m01", 6),
            MethodResult("m02", METHODS["m02"], Status.PARTIAL, scores=[ScaleScore("Сумма баллов", 4.0)],
                         interpretation="Вы набрали 4 балла", answered=2, total=3),
            MethodResult.error("m03", METHODS["m03"], "Ошибка при подсчёте", total=3),
        ]
        self.text = to_text(collect(results + [ok_result("m01")], "student-01"))

    def test_header_and_summary(self):
        self.assertIn("ПОРТРЕТ ЛИЧНОСТИ", self.text)
        self.assertIn("student-01", self.text)
        self.assertIn("готово 1, частично 1, ошибок 1, нет данных 17", self.text)

    def test_results_shown(self):
        self.assertIn(f"1. {METHODS['m01']} — готово, отвечено 3 из 3", self.text)
        self.assertIn("Сумма баллов: 6 (уровень: средний)", self.text)
        self.assertIn("Сумма баллов: 4\n", self.text)  # 4.0 печатается как 4
        self.assertIn("результат приблизительный", self.text)
        self.assertIn("Причина: Ошибка при подсчёте", self.text)

    def test_no_data_listed_compactly(self):
        self.assertIn("Нет данных:", self.text)
        self.assertIn(f"20. {METHODS['m20']} — Результат не получен", self.text)

    def test_warnings_shown(self):
        self.assertIn("Предупреждения:", self.text)
        self.assertIn("повторный результат", self.text)


if __name__ == "__main__":
    unittest.main()
