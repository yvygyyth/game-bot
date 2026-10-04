"""便捷入口：不安装也能直接跑。

    python main.py run --dry-run
    python main.py capture -o logs/screenshots/a.png

等价于 ``gamebot ...``（装好之后用 console script 更顺手）。
"""

from __future__ import annotations

import sys
from pathlib import Path

SRC = Path(__file__).resolve().parent / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from gamebot.__main__ import main  # noqa: E402

if __name__ == "__main__":
    raise SystemExit(main())
