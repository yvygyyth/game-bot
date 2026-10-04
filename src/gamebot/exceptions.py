"""框架异常。

分层原则：

* 原子层（L1-L5）**尽量不抛异常**，用 ``ActionResult.error`` 表达失败 ——
  因为失败是常态（找不到图、超时），异常太贵也太吵。
* 只有"装配期 / 不可恢复"的问题才抛异常：配置写错、后端库没装、
  模板目录不存在、流程定义自相矛盾……这些应该在启动时就炸，而不是跑一半才炸。
"""

from __future__ import annotations

__all__ = [
    "BackendError",
    "BackendUnavailable",
    "ConfigError",
    "FlowError",
    "GameBotError",
    "StepFailed",
    "TemplateNotFoundError",
    "TimeoutExceeded",
]


class GameBotError(Exception):
    """本框架所有异常的基类。"""


# --------------------------------------------------------------------------- #
# 配置 / 装配
# --------------------------------------------------------------------------- #
class ConfigError(GameBotError):
    """配置文件缺失、字段非法、取值越界。"""


class BackendError(GameBotError):
    """后端（截图 / 输入）运行期故障。"""


class BackendUnavailable(BackendError):
    """后端依赖库没装，或当前平台不支持该后端。

    典型场景：在非 Windows 上选了 windows 后端，或没装 ``pywin32`` / ``adbutils``。
    """


class TemplateNotFoundError(GameBotError):
    """模板图文件不存在。

    这属于装配期错误 —— 模板路径写错应该在启动时发现，而不是等到某个分支才报 NOT_FOUND。
    """


# --------------------------------------------------------------------------- #
# 流程
# --------------------------------------------------------------------------- #
class FlowError(GameBotError):
    """流程定义非法：初始状态不存在、转移指向未定义状态、节点重复……"""


class StepFailed(GameBotError):
    """执行层在"必须成功"策略下遇到失败，向上抛出以中断流程。"""


class TimeoutExceeded(GameBotError):
    """某个步骤 / 整个流程超过预算时间。"""
