"""Контракт методики и справочник методик.

Каждая методика модуля — это класс-наследник MethodBlock.
Движок опроса работает с методиками только через этот контракт и ничего
не знает о том, как устроена конкретная методика внутри.

Правила контракта (подробнее — docs/contract.md):

1. id и name методики берутся из справочника METHODS.
2. get_questions() возвращает все вопросы методики:
   - у каждого вопроса method_id равен id методики;
   - id вопросов не повторяются;
   - order идёт по порядку: 1, 2, 3, ...
3. process(answers) получает словарь, где есть ВСЕ id вопросов методики:
   - Answer со значением — пользователь ответил;
   - Answer со skipped=True — пользователь отказался отвечать;
   - None — пользователь до вопроса не дошёл.
4. process(answers) возвращает MethodResult:
   - method_id и method_name совпадают с методикой;
   - answered — сколько вопросов отвечено, total — сколько всего вопросов.
5. Пропуски — обычная ситуация, а не ошибка: process не должен из-за них
   падать, а должен вернуть статус PARTIAL или NO_DATA.
   Какой именно статус — решает общее правило result_status(answered, total).
   Если process всё же выбросит исключение, движок поймает его и поставит
   методике статус ERROR — остальные методики продолжат работу.
6. Методика не хранит состояние между вызовами: process можно вызвать
   повторно с теми же ответами и получить тот же результат.
"""

from __future__ import annotations

from abc import ABC, abstractmethod

from portrait.core.models import MethodAnswers, MethodResult, Question, Status


# Официальный список 20 методик. Порядок в словаре — порядок прохождения опроса.
METHODS: dict[str, str] = {
    "m01": "Оценка особенностей личности",
    "m02": "Индекс устойчивости идентичности",
    "m03": "Критическое мышление",
    "m04": "Когнитивная рефлексия",
    "m05": "Когнитивные стили",
    "m06": "Методика СОРЕ",
    "m07": "Методика измерения альтруистических установок",
    "m08": "Метакогнитивная включенность в деятельность",
    "m09": "Методика СО",
    "m10": "Методика СПД",
    "m11": "ПОАК",
    "m12": "Мотивация учебной деятельности",
    "m13": "СЖО",
    "m14": "Стили коммуникации",
    "m15": "Тест-опросник критического мышления (КМ)",
    "m16": "Потребность в познании",
    "m17": "Формально-динамические свойства индивидуальности (темперамент)",
    "m18": "Фундаментальные свойства личности",
    "m19": "Черты характера",
    "m20": "Эмоциональный интеллект",
}


def method_name(method_id: str) -> str:
    """Возвращает название методики по id.

    Выбрасывает KeyError с понятным сообщением, если такой методики нет в справочнике.
    """
    if method_id not in METHODS:
        raise KeyError(f"Методики {method_id!r} нет в справочнике METHODS")
    return METHODS[method_id]


# Минимальная доля отвеченных вопросов, при которой результат методики ещё считается.
# Если отвечено меньше — результата нет (NO_DATA): по нескольким ответам выводы делать нельзя.
MIN_ANSWERED_SHARE = 0.5


def result_status(answered: int, total: int) -> Status:
    """Общее правило: какой статус ставить методике по числу ответов.

    - отвечено всё                         → OK;
    - отвечено не меньше MIN_ANSWERED_SHARE → PARTIAL (результат с оговоркой);
    - отвечено меньше или ничего           → NO_DATA.

    Пропущенные вопросы (Answer.skip) и непройденные (None) отвеченными не считаются.
    """
    if total <= 0 or answered <= 0:
        return Status.NO_DATA
    if answered >= total:
        return Status.OK
    if answered / total >= MIN_ANSWERED_SHARE:
        return Status.PARTIAL
    return Status.NO_DATA


class MethodBlock(ABC):
    """Базовый класс методики.

    В наследнике нужно задать атрибуты id и name и реализовать
    два метода: get_questions() и process(answers).

    Пример:

        class DemoMethod(MethodBlock):
            id = "m01"
            name = METHODS["m01"]

            def get_questions(self) -> list[Question]:
                ...

            def process(self, answers: MethodAnswers) -> MethodResult:
                ...
    """

    id: str = ""    # id из справочника METHODS, например "m01"
    name: str = ""  # название из справочника METHODS

    @abstractmethod
    def get_questions(self) -> list[Question]:
        """Возвращает все вопросы методики в порядке показа."""

    @abstractmethod
    def process(self, answers: MethodAnswers) -> MethodResult:
        """Считает результат методики по ответам пользователя.

        answers — словарь {id вопроса: Answer или None} по всем вопросам методики.
        """

    def __repr__(self) -> str:
        return f"<{type(self).__name__} {self.id} «{self.name}»>"
