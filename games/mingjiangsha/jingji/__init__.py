"""竞技场 —— 名将杀的一个脚本功能。

流程（你给的那六张截图里的四步跳转）::

    首页 ──点「竞技」──▶ 竞技场 ──点「创建队伍」──▶ 队伍面板
                                                      │
                       开始匹配 ◀──点「开始匹配」── 点「添加伙伴」
                                                      │
                                                    已准备

**当前进度：第一步（首页 → 竞技入口）做完并验证过。**

后面三步要先补模板，原因见下面"环境限制"。

## 环境限制：为什么后面几步还没做

这个 agent 环境**拦掉了鼠标注入** —— 连最底层的 ``SetCursorPos`` 都返回失败：

```
SetCursorPos 返回: 0     GetLastError: 0     光标: 不动
本进程会话 1 / 前台进程会话 1    （不是会话隔离）
ClipCursor: 全屏                （不是被游戏锁了光标）
OpenInputDesktop: 句柄有效       （同一个输入桌面）
```

截屏能拿到真实画面，但注入不了输入 —— 所以"点进游戏再截图裁模板"这条路走不通。
你自己在 DSH 外面跑脚本时是正常的。

后面三步的模板可以**从你的原生截图里裁**（你那几张是 1920x1112 原生，
剥掉 1px 边框 + 31px 标题栏之后和客户区 1:1，裁出来是干净像素）。
这条路已经验证过了 —— 竞技的悬浮模板就是这么裁的，在干净屏幕上余量 +0.300。

## 命令

```bash
python -m games check  mingjiangsha/jingji    # 静态自检（不需要游戏）
python -m games probe  mingjiangsha/jingji    # 真机探针：现在屏幕上能认出竞技入口吗
```
"""

from __future__ import annotations

from pathlib import Path

from gamebot.config.schema import AppConfig
from gamebot.flow import EngineOptions, Scenario, UnknownPolicy
from gamebot.state import PageTree

from .. import game as _game
from .graph import build_graph
from .pages import FEATURE_PAGES

SLUG = "jingji"
TITLE = "竞技场"
DESCRIPTION = "首页点竞技 → 创建队伍 → 添加伙伴 → 开始匹配"

TEMPLATES_DIR = "games/mingjiangsha/jingji/templates"

#: 抓下来的"参考画面"放这儿，自检用它验证"认得准不准"。生成物，不入库。
FIXTURES_DIR = "games/mingjiangsha/fixtures"

#: 声明"资源缺失时 check 可以自动帮我抓一张"。
#: **抓的时候游戏必须在首页** —— 抓到别的页面，自检会明确报"认不出来"。
AUTO_PREPARE = True


def build_config() -> AppConfig:
    config = _game.base_config()
    config.name = f"{_game.SLUG}/{SLUG}"
    config.vision.extra_template_dirs = (TEMPLATES_DIR,)
    config.timing.tick_interval = 0.4
    return config


def build_tree() -> PageTree:
    tree = _game.new_tree()
    for page, parent in FEATURE_PAGES:
        tree.add(page, parent)
    return tree


def build_scenario() -> Scenario:
    return Scenario(
        name=f"{_game.SLUG}/{SLUG}",
        tree=build_tree(),
        graph=build_graph(),
        options=EngineOptions(
            tick_interval=0.4,
            max_runtime=180.0,
            on_unknown=UnknownPolicy.WAIT,
            unknown_grace=1.5,
        ),
    )


def prepare(*, force: bool = False) -> int:
    """抓一张当前画面存成参考图（fixture）。自检靠它验证认得准不准。

    幂等：已经存在就跳过（``force=True`` 才重抓）。

    **抓的时候游戏要在首页**：这个函数不知道也不猜"现在在哪一页"，
    抓到什么就是什么，认不出来由自检如实报告。
    """
    target = _game.PROJECT_ROOT / FIXTURES_DIR / "home.png"
    if target.is_file() and not force:
        return 0
    target.parent.mkdir(parents=True, exist_ok=True)

    from gamebot.bootstrap import build_session_from_config

    session = build_session_from_config(build_config())
    with session:
        frame = session.capture()
        result = frame.save(target)
    if not result.ok:
        raise RuntimeError(f"抓参考图失败: {result.message}")
    return 1


def selftest() -> list[str]:
    """静态自检：不需要游戏在跑，但需要参考图（``prepare()`` 抓）。

    还会拿 ``assets/`` 里那四张真实截图做回归（存在时）。
    """
    from .checks import run

    return run(build_config())


def probe() -> list[str]:
    """**真机探针**：抓一张当前画面，看能不能认出竞技入口。

    这是"找到竞技入口"最直接的验证方式 —— 需要游戏开着且在首页。
    """
    from .checks import probe_live

    return probe_live(build_config())


def _project_root() -> Path:
    """项目根（checks 用它拼 fixtures 的路径）。"""
    return _game.PROJECT_ROOT


__all__ = [
    "DESCRIPTION",
    "FIXTURES_DIR",
    "SLUG",
    "TEMPLATES_DIR",
    "TITLE",
    "build_config",
    "build_graph",
    "build_scenario",
    "build_tree",
    "prepare",
    "probe",
    "selftest",
]
