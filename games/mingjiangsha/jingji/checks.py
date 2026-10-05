"""竞技场 —— **只声明"检查什么"，逻辑在框架里**。

## 这个文件现在只有数据

以前这里有一整套检查实现（算 ROI 余量、跑顺序探测、渲染分数表、包装 Frame……）
约 460 行，其中**只有一批数字是这个游戏特有的**，其余每个脚本都会重写一遍。
现在逻辑在 :mod:`gamebot.vision.checks`，这里只留 :data:`CHECKS`。

好处不只是少写代码：**语义由框架保证一致**。比如"ROI 余量"的算法只有一份，
不会出现 A 脚本当成半径、B 脚本当成边长。修一次检查，所有脚本受益。

## 这里声明的东西，和它们各自防的是什么

* ``entry`` 的 ``roi`` + ``hover`` —— 名将杀首页的卡片**鼠标一悬停就往右上弹
  ``(+27, -41)``**。ROI 留小了，你一划过入口模板就滑出 ROI、匹配不到。
  这是**静态看代码完全看不出来**的错，只能跑到那一屏才发现；
* ``entry`` 的 ``origin`` —— 模板必须在自己那张资产图上拿满分。
  裁歪几像素在运行的画面上看不出来，但会让阈值变得很脆；
* ``sequences`` —— 验的是"按顺序找，第一个过阈值的正好是该点的那个"。
  这条**不是**"按钮之间分数差多少"：``开始匹配``在三种状态下都是 0.999
  （见 :mod:`.steps`），它本来就该在别的图上拿高分；
* ``groups`` —— 真机探针用：现在屏幕上认得出哪一页、走到队伍流程哪一步了。
"""

from __future__ import annotations

from pathlib import Path

from gamebot.types import Point
from gamebot.vision.checks import (
    ChecksSpec,
    EntryGroup,
    EntrySpec,
    SequenceSpec,
    run_checks,
    run_probe,
)

from ..game import PROJECT_ROOT as _GAME_ROOT
from ..shortcuts import (
    CONF_JINGJI,
    JINGJI_CENTER,
    JINGJI_ROI,
    JINGJI_TOLERANCE,
    T_JINGJI,
)
from . import FIXTURES_DIR
from .pages import CONF_TITLE, JINGJI_PAGE_ROI
from .steps import (
    CONF_BUTTON,
    T_ADD_PET,
    T_CREATE_TEAM,
    T_START_MATCH,
    T_TITLE,
    TEAM_ROI,
)

__all__ = ["CHECKS", "probe_live", "run"]

#: 资产图目录（四张真机截图）。**本地参考素材，不入库**，没有就自动跳过回归。
ASSETS_DIR = Path(__file__).resolve().parent / "assets"

#: 竞技场那三张（同一页的三种状态）。
JINGJI_STATES = ("jingji.png", "add-pet.png", "start.png")

CHECKS = ChecksSpec(
    title="竞技场",
    assets_dir=ASSETS_DIR,
    # 参考图是 ``prepare()`` 抓的，位置由**这个脚本**决定 ——
    # 框架不猜业务层的目录约定（猜就是第二份事实来源）。
    fixture_path=_GAME_ROOT / FIXTURES_DIR / "home.png",
    # 参考图抓的是**首页**，所以只要求认出「首页」那一组
    fixture_group="首页",
    states=JINGJI_STATES,
    entries=(
        EntrySpec(
            template=T_JINGJI,
            point=JINGJI_CENTER,
            confidence=CONF_JINGJI,
            tolerance=JINGJI_TOLERANCE,
            roi=JINGJI_ROI,
            # 悬停时卡片往右上弹 —— ROI 必须留得下这个位移
            hover=Point(27, -41),
            # 这张不是从资产图裁的：资产图里的 home.png 是**悬浮态**，
            # 卡片被放大 1.1 倍并位移，空闲模板在它上面只有 0.774，
            # 那是正常的，不是问题。所以不声明 origin。
            label="竞技入口",
        ),
        EntrySpec(
            template=T_TITLE,
            # **不要手算这个点**：标题的 ROI 就是"围着它框的"，所以期望中心
            # 就是 ROI 的中心。第一版我写的是 ``Point(roi.x + 60, roi.y + 40)``
            # 这种估出来的值，几何检查立刻报"模板摆下去会伸出 ROI" ——
            # 那个检查正是为了防这类手算错误而存在的。
            point=JINGJI_PAGE_ROI.center,
            confidence=CONF_TITLE,
            roi=JINGJI_PAGE_ROI,
            origin="jingji.png",
            label="竞技场标题",
        ),
    ),
    groups=(
        EntryGroup(
            name="首页",
            entries=(
                EntrySpec(
                    template=T_JINGJI,
                    point=JINGJI_CENTER,
                    confidence=CONF_JINGJI,
                    tolerance=JINGJI_TOLERANCE,
                    roi=JINGJI_ROI,
                    hover=Point(27, -41),
                    label="竞技入口",
                ),
            ),
        ),
        EntryGroup(
            name="竞技场",
            entries=(
                EntrySpec(
                    template=T_TITLE,
                    point=JINGJI_PAGE_ROI.center,
                    confidence=CONF_TITLE,
                    roi=JINGJI_PAGE_ROI,
                    origin="jingji.png",
                    label="竞技场标题",
                ),
            ),
        ),
        # 这三个**不参与成败**：它们只是告诉你在队伍流程的哪一步
        EntryGroup(
            name="队伍",
            required=False,
            entries=(
                EntrySpec(
                    template=T_CREATE_TEAM,
                    point=TEAM_ROI.center,
                    confidence=CONF_BUTTON,
                    roi=TEAM_ROI,
                    origin="jingji.png",
                    label="创建队伍",
                ),
                EntrySpec(
                    template=T_ADD_PET,
                    point=TEAM_ROI.center,
                    confidence=CONF_BUTTON,
                    roi=TEAM_ROI,
                    origin="add-pet.png",
                    label="添加伙伴",
                ),
                EntrySpec(
                    template=T_START_MATCH,
                    point=TEAM_ROI.center,
                    confidence=CONF_BUTTON,
                    roi=TEAM_ROI,
                    origin="start.png",
                    label="开始匹配",
                ),
            ),
        ),
    ),
    sequences=(
        SequenceSpec(
            templates=(T_CREATE_TEAM, T_ADD_PET, T_START_MATCH),
            names=("创建队伍", "添加伙伴", "开始匹配"),
            roi=TEAM_ROI,
            confidence=CONF_BUTTON,
            expected={
                "jingji.png": T_CREATE_TEAM,
                "add-pet.png": T_ADD_PET,
                "start.png": T_START_MATCH,
            },
        ),
    ),
)


# --------------------------------------------------------------------------- #
# 两个入口（业务层的契约：``selftest()`` 给 games selftest，
# ``probe()`` 给 games probe）
# --------------------------------------------------------------------------- #
def run(config) -> list[str]:
    """静态自检。逻辑在框架里，这里只把 :data:`CHECKS` 交过去。"""
    return run_checks(CHECKS, config)


def probe_live(config) -> list[str]:
    """真机探针。"""
    return run_probe(CHECKS, config)
