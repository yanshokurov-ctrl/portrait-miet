from pathlib import Path  # Для работы с путями к файлам
import json               # Для чтения JSON-файлов

# Справочник методик — по нему определяем порядок
from ..core.contracts import METHODS, MethodBlock
from ..core.errors import SourceError

# Импортируем наш класс-методику из соседней папки methods
from ..methods.json_method import JsonMethod

# И импортируем контракт от главного разработчика
from .base import QuestionSource

# Папка с методиками внутри пакета: portrait/methods/data.
# Считаем путь от этого файла, чтобы он не зависел от того, откуда запущена программа.
DEFAULT_METHODS_FOLDER = Path(__file__).resolve().parent.parent / "methods" / "data"


class JsonSource(QuestionSource):
    """
    Загрузчик методик из файлов.

    Движок вызывает только метод load_methods() и получает готовые объекты методик.
    Откуда они взялись — движку не важно.
    """

    def __init__(self, methods_folder: str | Path = DEFAULT_METHODS_FOLDER):
        # При создании мы запоминаем путь до папки с файлами.
        self.folder_path = Path(methods_folder)  # Преобразуем строку в объект пути

    def load_methods(self) -> list[MethodBlock]:
        if not self.folder_path.is_dir():
            raise SourceError(f"Папка с методиками не найдена: {self.folder_path}")

        methods_by_id = {}

        # Проходимся по всем файлам в папке
        for file_path in sorted(self.folder_path.glob("*.json")):
            try:
                with open(file_path, encoding="utf-8") as f:
                    data = json.load(f)  # Считываем сырой словарь из файла
                if not isinstance(data, dict):
                    raise ValueError("в файле должен быть объект { ... }")

                # Создаём экземпляр нашей методики!
                method = JsonMethod(data)

            except (OSError, json.JSONDecodeError, ValueError) as e:
                raise SourceError(f"Ошибка при чтении {file_path.name}: {e}") from e

            if method.id in methods_by_id:
                raise SourceError(f"Ошибка при чтении {file_path.name}: методика {method.id} уже загружена из другого файла")
            methods_by_id[method.id] = method

        # Методики должны возвращаться строго в том порядке, как в справочнике METHODS
        return [methods_by_id[method_id] for method_id in METHODS if method_id in methods_by_id]
