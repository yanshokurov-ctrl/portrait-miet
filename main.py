"""Точка входа модуля «Портрет личности».

Запуск опроса в консоли:

    python main.py
    python main.py --out результат.json --respondent student-01
    python main.py --data путь/к/папке/с/методиками
"""

import argparse
import sys

from portrait.ui.console import run


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Портрет личности — консольный опрос")
    parser.add_argument("--data", help="папка с JSON-методиками (по умолчанию portrait/methods/data)")
    parser.add_argument("--out", default="portrait.json", help="куда сохранить отчёт в JSON (по умолчанию portrait.json)")
    parser.add_argument("--respondent", help="id респондента (по умолчанию создаётся анонимный)")
    args = parser.parse_args(argv)
    return run(methods_folder=args.data, out_path=args.out, respondent_id=args.respondent)


if __name__ == "__main__":
    sys.exit(main())
