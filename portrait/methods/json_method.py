"""Методика, описанная в JSON-файле.

Формат файла (подробно — docs/method_format.md):

    {
      "method_id": "m02",
      "instruction": "Текст инструкции для респондента",
      "type": "scale",                                   # тип вопросов по умолчанию
      "options": [{"value": 1, "label": "Не согласен"}, ...],   # варианты по умолчанию
      "questions": [
        {"text": "Текст вопроса"},                       # берёт type и options методики
        {"text": "Другой вопрос", "type": "choice",
         "options": [{"value": "а", "label": "..."}]}    # свои тип и варианты
      ],
      "scoring": { ... }                                 # ключи — см. methods/scoring.py
    }

id вопроса (m02_q01), method_id и order в файле не пишутся —
их проставляет JsonMethod по порядку вопросов.

Если раздела "scoring" нет, балл считается временно — как сумма числовых ответов.
"""

from portrait.core.contracts import MIN_ANSWERED_SHARE, MethodBlock, METHODS, result_status
from portrait.core.models import MethodAnswers, MethodResult, Option, Question, ScaleScore, Status
from portrait.methods.scoring import compute_scores, interpret, points_word, validate_scoring

__all__ = ["JsonMethod", "points_word"]


class JsonMethod(MethodBlock):
    def __init__(self, method_data: dict):
        method_id = method_data.get("method_id")
        if method_id not in METHODS:
            raise ValueError(f"method_id {method_id!r} нет в справочнике METHODS")
        if not isinstance(method_data.get("questions"), list) or not method_data["questions"]:
            raise ValueError("нет поля questions или список вопросов пуст")

        self.id = method_id
        self.name = METHODS[method_id]
        self.instruction = method_data.get("instruction", "")
        self.method_data = method_data
        # Вопросы собираем сразу: ошибка в файле видна при загрузке, а не посреди опроса
        self.questions = [
            self._make_question(number, question_dict)
            for number, question_dict in enumerate(method_data["questions"], start=1)
        ]

        self.scoring = method_data.get("scoring")
        if self.scoring is not None:
            try:
                validate_scoring(self.scoring, self.questions)
            except ValueError as error:
                raise ValueError(f"ключи: {error}") from error

    def _make_question(self, number: int, question_dict: dict) -> Question:
        # id, method_id и order проставляем сами по порядку вопросов.
        # Тип и варианты ответа — свои у вопроса или общие для методики.
        try:
            return Question(
                id=f"{self.id}_q{number:02d}",
                method_id=self.id,
                text=question_dict["text"],
                order=number,
                type=question_dict.get("type", self.method_data.get("type", "scale")),
                options=[Option.from_dict(option)
                         for option in question_dict.get("options", self.method_data.get("options", []))],
            )
        except KeyError as error:
            raise ValueError(f"вопрос {number}: нет поля {error}") from error

    def get_questions(self) -> list[Question]:
        # Отдаём копию, чтобы движок случайно не изменил список вопросов методики
        return list(self.questions)

    def process(self, answers: MethodAnswers) -> MethodResult:
        total = len(self.questions)
        # Отвеченные — те, где ответ есть и он не пропущен.
        # None (не дошёл до вопроса) и Answer.skip (отказался отвечать) не считаются.
        values = {}
        for question in self.questions:
            answer = answers.get(question.id)
            if answer is not None and not answer.skipped:
                values[question.order] = answer.value

        # Статус по общему правилу из contracts.py
        status = result_status(len(values), total)
        if status == Status.NO_DATA:
            if not values:
                reason = "Нет ни одного ответа"
            else:
                reason = (f"Отвечено {len(values)} из {total} вопросов — "
                          f"меньше допустимого минимума ({MIN_ANSWERED_SHARE:.0%})")
            return MethodResult.no_data(self.id, self.name, reason, total=total)

        if self.scoring is not None:
            scores = compute_scores(self.scoring, values)
            interpretation = interpret(self.scoring, scores)
        else:
            # Временный подсчёт для методик без ключей: сумма числовых ответов
            total_score = sum(
                value for value in values.values()
                if isinstance(value, (int, float)) and not isinstance(value, bool)
            )
            scores = [ScaleScore(scale='Сумма баллов', raw=total_score)]
            interpretation = f"Вы набрали {total_score} {points_word(total_score)}"

        return MethodResult(
            method_id=self.id,
            method_name=self.name,
            status=status,  # OK или PARTIAL (есть пропуски)
            scores=scores,
            interpretation=interpretation,
            answered=len(values),
            total=total,
        )
