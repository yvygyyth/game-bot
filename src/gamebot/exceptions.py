"""框架异常。

分层原则：

* 原子层（L1-L5）**尽量不抛异常**，用 ``ActionResult.error`` 表达失败 ——
  因为失败是常态（找不到图、超时），异常太贵也太吵。
* 只有"装配期 / 不可恢复"的问题才抛异常：配置写错、后端库没装、
  模板目录不存在、流程定义自相矛盾……这些应该在启动时就炸，而不是跑一半才炸。

**唯一的例外是 :class:`Cancelled`** —— 它不表示"失败"，表示"别再继续了"。
返回值表达"这次尝试的结果"，异常表达"中止"，这个分界见它的 docstring。
"""

from __future__ import annotations

__all__ = [
    "BackendError",
    "BackendUnavailable",
    "Cancelled",
    "ConfigError",
    "FlowError",
    "GameBotError",
    "StateError",
    "StepFailed",
    "TemplateNotFoundError",
    "TimeoutExceeded",
]


class GameBotError(Exception):
    """本框架所有异常的基类。"""


class Cancelled(BaseException):
    """中止请求。**不是错误，是控制流。**

    中断长等待（``wait_any_of`` / ``wait_all_of`` / ``wait_until`` /
    ``wait_stable`` / ``wait_disappear`` / ``Session.sleep``）靠它。

    ⚠️ 刻意继承 ``BaseException`` 而不是 ``Exception``：

    框架里到处是 ``except Exception as exc: return ActionResult.error(...)``，
    用途是把后端故障（模板缺失、adb 掉线）转成结果。中止**绝不能**被它们吞掉 ——
    否则"点了停止没反应"会变成最难查的一类 bug。
    ``KeyboardInterrupt`` / ``SystemExit`` 出于同样的理由也是 ``BaseException``。

    ⚠️ 不要写裸 ``except:``。它会连中止一起吞掉。

    传播途中 ``finally`` 照常执行，这一点很关键：``hotkey`` 的按键释放、
    ``drag`` 的 ``mouseUp`` 不会被跳过 —— 中止不会留下卡住的 Ctrl
    或被拖住的整个桌面。

    它**不进任何重试逻辑**：``RetryPolicy.retry_on`` 枚举的是
    ``ActionStatus``，而中止是异常，天然不参与重试。
    """

    def __init__(self, reason: str = "已请求中止") -> None:
        super().__init__(reason)
        self.reason = reason


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
# 状态 / 流程
# --------------------------------------------------------------------------- #
class StateError(GameBotError):
    """状态树定义非法：id 重复、父页面不存在、叠加层带了子页面……

    和 :class:`FlowError` 分开：一个是"我认不出游戏"，
    一个是"我不知道该干什么"，报错时得能分清是哪个错了。
    """


class FlowError(GameBotError):
    """流程定义非法：初始状态不存在、转移指向未定义状态、节点重复……"""


class StepFailed(GameBotError):
    """执行层在"必须成功"策略下遇到失败，向上抛出以中断流程。"""


class TimeoutExceeded(GameBotError):
    """某个步骤 / 整个流程超过预算时间。"""
