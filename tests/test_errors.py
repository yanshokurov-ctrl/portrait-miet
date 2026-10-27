"""Тесты исключений (portrait/core/errors.py)."""

import unittest

from portrait.core.errors import (
    BlockError,
    InvalidAnswerError,
    InvalidResultError,
    PortraitError,
    SessionError,
    SourceError,
)


class ErrorsTests(unittest.TestCase):

    def test_all_errors_are_portrait_errors(self):
        # Интерфейс ловит любую ошибку модуля одной строкой: except PortraitError
        for error_class in (SourceError, BlockError, InvalidResultError, SessionError, InvalidAnswerError):
            with self.subTest(error_class=error_class.__name__):
                self.assertTrue(issubclass(error_class, PortraitError))

    def test_message_is_kept(self):
        self.assertEqual(str(SourceError("Папка не найдена")), "Папка не найдена")


if __name__ == "__main__":
    unittest.main()
