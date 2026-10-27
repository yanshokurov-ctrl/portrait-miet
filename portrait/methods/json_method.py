"""Методика, описанная в JSON-файле.

Формат файла:

    {
      "method_id": "m01",
      "questions": [
        {"text": "Текст вопроса", "type": "scale",
         "options": [{"value": 1, "label": "Не согласен"}, ...]}
      ]
    }

id вопроса (m01_q01), method_id и order в файле не пишутся —
их проставляет JsonMethod по порядку вопросов.
"""

from portrait.core.contracts import MIN_ANSWERED_SHARE, MethodBlock, METHODS, result_status
from portrait.core.models import MethodAnswers, MethodResult, Option, Question, ScaleScore, Status


def points_word(number: int | float) -> str:
    """Склоняет слово «балл»: 1 балл, 2 балла, 5 баллов, 2.5 балла."""
    if isinstance(number, float) and not number.is_integer():
        return "балла"
    number = abs(int(number))
    if number % 10 == 1 and number % 100 != 11:
        return "балл"
    if 2 <= number % 10 <= 4 and not 12 <= number % 100 <= 14:
        return "балла"
    return "баллов"


class JsonMethod(MethodBlock):
    def __init__(self, method_data: dict):
        method_id = method_data.get("method_id")
        if method_id not in METHODS:
            raise ValueError(f"method_id {method_id!r} нет в справочнике METHODS")
        if not isinstance(method_data.get("questions"), list) or not method_data["questions"]:
            raise ValueError("нет поля questions или список вопросов пуст")

        self.id = method_id
        self.name = METHODS[method_id]
        self.method_data = method_data
        # Вопросы собираем сразу: ошибка в файле видна при загрузке, а не посреди опроса
        self.questions = [
            self._make_question(number, question_dict)
            for number, question_dict in enumerate(method_data["questions"], start=1)
        ]

    def _make_question(self, number: int, question_dict: dict) -> Question:
        # id, method_id и order проставляем сами по порядку вопросов
        try:
            return Question(
                id=f"{self.id}_q{number:02d}",
                method_id=self.id,
                text=question_dict["text"],
                order=number,
                type=question_dict.get("type", "scale"),  # По умолчанию шкала (если типа нет)
                options=[Option.from_dict(option) for option in question_dict.get("options", [])],
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
        answered = [
            answer for answer in (answers.get(question.id) for question in self.questions)
            if answer is not None and not answer.skipped
        ]

        # Статус по общему правилу из contracts.py
        status = result_status(len(answered), total)
        if status == Status.NO_DATA:
            if not answered:
                reason = "Нет ни одного ответа"
            else:
                reason = (f"Отвечено {len(answered)} из {total} вопросов — "
                          f"меньше допустимого минимума ({MIN_ANSWERED_SHARE:.0%})")
            return MethodResult.no_data(self.id, self.name, reason, total=total)

        # Временный подсчёт до шага 10: сумма числовых ответов
        total_score = sum(
            answer.value for answer in answered
            if isinstance(answer.value, (int, float)) and not isinstance(answer.value, bool)
        )

        return MethodResult(
            method_id=self.id,
            method_name=self.name,
            status=status,  # OK или PARTIAL (есть пропуски)
            scores=[ScaleScore(scale='Сумма баллов', raw=total_score)],
            interpretation=f"Вы набрали {total_score} {points_word(total_score)}",
            answered=len(answered),
            total=total,
        )
