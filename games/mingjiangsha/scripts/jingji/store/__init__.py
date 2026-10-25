"""竞技场的状态仓库 —— **跨运行**的记忆。

一个仓库一个文件，本包**只做转发**（和 ``steps/__init__.py`` 同一套规矩）：

* :data:`.runs.RUNS` —— 累计局数（``jingji.runs``）。

以后再加"今天领了几次奖励"这类要跨运行记住的东西，就在这里加一个文件、
在下面导出一行。
"""

from __future__ import annotations

from .runs import RUNS

__all__ = ["RUNS"]
