"""Движок опроса.

Ведёт пользователя по вопросам всех методик, принимает ответы
и передаёт их методикам на подсчёт.

Движок не содержит логики конкретных методик и ничего не знает
об интерфейсе: консоль, окно или обёртка для тестирования работают
с ним одинаково.

Пример использования:

    session = SurveySession(JsonSource().load_methods())
    while not session.is_finished():
        question = session.current_question()
        ...                        # показать вопрос пользователю
        session.answer(value)      # или session.skip() / session.back()
    results = session.finish()     # список MethodResult — передать в сборщик

Опрос можно завершить в любой момент: finish() вызывается и до конца
вопросов, тогда непройденные вопросы попадут в методики как None.

Кто что делает (шаг 4 этапа 1):
    основной разработчик — __init__(), finish();
    разработчик 1        — current_question(), is_finished(), progress(), next(), back();
    разработчик 2        — answer(), skip(), grouped_answers().

Состояние опроса (общее для всех методов):
    self._methods   — методики в порядке справочника METHODS;
    self._broken    — {id методики: причина} для методик, у которых не удалось получить вопросы;
    self._questions — все вопросы всех методик подряд, в порядке показа;
    self._answers   — {id вопроса: Answer} — данные ответы и пропуски;
                      вопроса, до которого пользователь не дошёл, здесь нет;
    self._index     — номер текущего вопроса в self._questions (с 0);
                      равен len(self._questions), когда вопросы закончились.
"""

from __future__ import annotations

from dataclasses import dataclass

from portrait.core.contracts import METHODS, MethodBlock
from portrait.core.errors import InvalidAnswerError, SessionError  # noqa: F401 — нужны разработчикам 1 и 2
from portrait.core.models import Answer, MethodAnswers, MethodResult, Question


@dataclass(frozen=True)
class Progress:
    """Прогресс прохождения опроса.

    number   — номер текущего вопроса, начиная с 1;
               когда вопросы закончились — равен total;
    total    — сколько всего вопросов в опросе;
    answered — на сколько вопросов дан ответ (пропуски не считаются).
    """

    number: int
    total: int
    answered: int


class SurveySession:
    """Один проход опроса одним пользователем."""

    # ------------------------------------------------------------------
    # Основной разработчик
    # ------------------------------------------------------------------

    def __init__(self, methods: list[MethodBlock]):
        """Готовит опрос: упорядочивает методики и собирает их вопросы.

        Выбрасывает SessionError, если методик нет, методики нет
        в справочнике или одна методика передана дважды — это ошибки
        источника вопросов, а не пользователя.

        Если у методики не получилось взять вопросы (get_questions() упал
        или вернул неверные данные), опрос не останавливается: методика
        запоминается в self._broken, а в finish() получает статус ERROR.
        """
        if not methods:
            raise SessionError("Нет ни одной методики для опроса")

        seen_ids: set[str] = set()
        for method in methods:
            if method.id not in METHODS:
                raise SessionError(f"Методики {method.id!r} нет в справочнике METHODS")
            if method.id in seen_ids:
                raise SessionError(f"Методика {method.id} передана дважды")
            seen_ids.add(method.id)

        directory_order = list(METHODS)
        self._methods: list[MethodBlock] = sorted(methods, key=lambda method: directory_order.index(method.id))
        self._broken: dict[str, str] = {}
        self._questions: list[Question] = []
        self._answers: dict[str, Answer] = {}
        self._index = 0

        for method in self._methods:
            # Ловим любое исключение: чужая методика не должна ронять весь опрос.
            try:
                self._questions.extend(self._load_questions(method))
            except Exception as error:
                self._broken[method.id] = f"Не удалось получить вопросы: {error}"

    def _load_questions(self, method: MethodBlock) -> list[Question]:
        """Берёт вопросы методики и проверяет, что они соответствуют контракту."""
        questions = method.get_questions()
        if not isinstance(questions, list) or not questions:
            raise ValueError("get_questions() должен вернуть непустой список вопросов")

        known_ids = {question.id for question in self._questions}
        for question in questions:
            if not isinstance(question, Question):
                raise ValueError(f"в списке вопросов {type(question).__name__} вместо Question")
            if question.method_id != method.id:
                raise ValueError(f"вопрос {question.id} относится к методике {question.method_id}")
            if question.id in known_ids:
                raise ValueError(f"id вопроса {question.id} повторяется")
            known_ids.add(question.id)

        return sorted(questions, key=lambda question: question.order)

    def finish(self) -> list[MethodResult]:
        """Передаёт ответы методикам и возвращает их результаты.

        Результаты идут в порядке справочника, по одному на каждую методику опроса.
        Если методика упала или вернула что-то не то, вместо её результата
        ставится MethodResult со статусом ERROR — остальные методики считаются как обычно.
        """
        grouped = self.grouped_answers()
        results = []
        for method in self._methods:
            if method.id in self._broken:
                results.append(MethodResult.error(method.id, method.name, self._broken[method.id]))
            else:
                results.append(self._run_method(method, grouped[method.id]))
        return results

    def _run_method(self, method: MethodBlock, answers: MethodAnswers) -> MethodResult:
        """Вызывает process() одной методики и проверяет результат."""
        total = len(answers)
        # Ловим любое исключение: чужая методика не должна ронять весь опрос.
        try:
            # Передаём копию, чтобы методика не могла испортить ответы.
            result = method.process(dict(answers))
        except Exception as error:
            return MethodResult.error(method.id, method.name,
                                      f"Ошибка при подсчёте: {type(error).__name__}: {error}", total=total)

        if not isinstance(result, MethodResult):
            return MethodResult.error(method.id, method.name,
                                      f"process() вернул {type(result).__name__} вместо MethodResult", total=total)
        if result.method_id != method.id:
            return MethodResult.error(method.id, method.name,
                                      f"process() вернул результат другой методики: {result.method_id!r}", total=total)
        return result

    # ------------------------------------------------------------------
    # Разработчик 1: показ вопросов и навигация (выполнено написание методов)
    # ------------------------------------------------------------------

    def current_question(self) -> Question | None:
        """Возвращает текущий вопрос или None, если вопросы закончились."""
        # добавлено разработчиком №1 в ходе шага 4
        if self._index < len(self._questions):
            return self._questions[self._index]
        else:
            return None

    def is_finished(self) -> bool:
        """True, если пользователь прошёл все вопросы (текущего вопроса нет).

        Опрос без вопросов (все методики сломаны) сразу считается пройденным.
        Если пользователь вернулся назад с конца опроса, это снова False.
        """
        # добавлено разработчиком №1 в ходе шага 4
        return self.current_question() is None

    def progress(self) -> Progress:
        """Возвращает прогресс: номер текущего вопроса, сколько всего, сколько отвечено.

        Пример: на 3-м вопросе из 10, отвечено 2 → Progress(number=3, total=10, answered=2).
        Пропущенные вопросы в answered не считаются.
        Когда вопросы закончились, number равен total.
        """
        # добавлено разработчиком №1 в ходе шага 4

        # Считаем количество ответов (пропуски не считаются)
        answered_count = sum(1 for answer in self._answers.values() if not answer.skipped)

        # Номер текущего вопроса; когда вопросы закончились — равен общему числу (0, если вопросов нет)
        current_number = self._index + 1 if not self.is_finished() else len(self._questions)

        return Progress(current_number, len(self._questions), answered_count)

    def next(self) -> None:
        """Переходит к следующему вопросу.

        Нужен, когда пользователь вернулся назад и идёт вперёд, не меняя ответ.
        Перейти можно, только если на текущий вопрос уже дан ответ или он пропущен,
        иначе — SessionError («Сначала ответьте на вопрос или пропустите его»).
        Если вопросы закончились — SessionError.
        """
        # добавлено разработчиком №1 в ходе шага 4

        # Проверяем, есть ли вообще следующий шаг
        if self.is_finished():
            raise SessionError("Вопросов больше нет")
        
        # Получаем ID текущего вопроса
        current_qid = self.current_question().id

        """
        Проверяем, есть ли у нас ответ для этого вопроса.
        Пропуски считаются за ответы, поэтому просто проверяем наличие ключа
        """
        if current_qid not in self._answers:
            raise SessionError(f"Ответьте на вопрос '{current_qid}' или пропустите его")

        # Всё хорошо, можно двигаться дальше
        self._index += 1

    def back(self) -> None:
        """Возвращается к предыдущему вопросу.

        Данный ответ при этом сохраняется: пользователь может его изменить
        через answer() или оставить и пойти дальше через next().
        На первом вопросе — SessionError («Это первый вопрос»).
        С конца опроса (is_finished() == True) — возвращает к последнему вопросу.
        """
        # добавлено разработчиком №1 в ходе шага 4
        if self._index == 0:
            raise SessionError("Вы уже находитесь на первом вопросе")
        
        # Просто двигаемся назад
        self._index -= 1

    # ------------------------------------------------------------------
    # Разработчик 2: приём ответов и группировка
    # ------------------------------------------------------------------

    def answer(self, value: int | float | str) -> None:
        """Принимает ответ на текущий вопрос и переходит к следующему.

        Ответ проверяется через current_question().is_valid_value(value).
        Неподходящий ответ — InvalidAnswerError с понятным текстом
        (для вопросов с вариантами — перечислить допустимые значения),
        при этом ничего не сохраняется и текущий вопрос не меняется.
        Если на вопрос уже отвечали (пользователь вернулся назад) — ответ заменяется.
        Если вопросы закончились — SessionError.
        """
        raise NotImplementedError("Разработчик 2: answer()")

    def skip(self) -> None:
        """Пропускает текущий вопрос (сохраняет Answer.skip) и переходит к следующему.

        Если на вопрос уже отвечали — ответ заменяется пропуском.
        Если вопросы закончились — SessionError.
        """
        raise NotImplementedError("Разработчик 2: skip()")

    def grouped_answers(self) -> dict[str, MethodAnswers]:
        """Группирует ответы по методикам.

        Возвращает {id методики: {id вопроса: Answer или None}}:
        - ключи — все методики опроса в порядке self._methods,
          у сломанных методик (self._broken) — пустой словарь {};
        - внутри — ВСЕ вопросы методики в порядке показа;
        - Answer — ответ или пропуск, None — пользователь до вопроса не дошёл.
        """
        raise NotImplementedError("Разработчик 2: grouped_answers()")
