"""Запуск агента без установки пакета и без console script.

Примеры:
    python main.py "покажи все бронирования"
    python main.py --json "найди бронирования Sally Brown"
    python main.py            # интерактивный режим
"""

from __future__ import annotations

import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent
SRC_DIR = PROJECT_ROOT / "src"

if str(SRC_DIR) not in sys.path:
    sys.path.insert(0, str(SRC_DIR))

from booker_agent.cli import main  # noqa: E402

if __name__ == "__main__":
    raise SystemExit(main())
