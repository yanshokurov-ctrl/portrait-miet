"""Абстрактный источник вопросов.

Движок опроса получает методики только через QuestionSource и не знает,
откуда они взялись: из JSON-файлов, из базы данных или из кода.
Чтобы подключить новый источник (например, базу данных от преподавателя),
достаточно написать наследника QuestionSource — ядро менять не нужно.
"""

from __future__ import annotations

from abc import ABC, abstractmethod

from portrait.core.contracts import MethodBlock


class QuestionSource(ABC):
    """Базовый класс источника вопросов."""

    @abstractmethod
    def load_methods(self) -> list[MethodBlock]:
        """Загружает все методики в порядке справочника METHODS.

        Если источник недоступен или данные повреждены, выбрасывает SourceError
        с понятным сообщением: в каком файле (или записи) ошибка и в чём она.
        """
