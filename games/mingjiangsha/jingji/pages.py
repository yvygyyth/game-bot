"""竞技场 —— 本功能的页面。

## 页面标识用什么

用**左上角的「竞技场」标题**（148x52）。实测它在三种状态下都是 **1.000** ——
这正是页面标识该有的性质：那三种状态都是同一个页面。

不能用的：**右侧队伍面板**。它在三种状态下长得完全不同
（空位+创建队伍 / 空位+添加伙伴 / 两个已准备的头像+开始匹配），
拿它当页面特征会导致"进到第二步就认不出自己在哪一页了"。

也不能用的：**背景**。竞技场背景是活的 —— 那个骑马的角色披风一直在飘，
三张图里背景像素完全不同。模板一旦框进背景，换一帧就废。

## ROI 为什么只框左上角

`:data:`JINGJI_PAGE_ROI` 只覆盖标题那一块。除了"更快"，
更重要的是**排除了中间那个「巅峰竞技场」大横幅** ——
它也含"竞技场"三个字，不做限制会有误命中的风险。

## 加新状态时要记住的两条（新模型）

1. **父子关系只表达 ROI 与消歧，不表示"祖先必须一直成立"。**
   所以"从首页进竞技场"之后不需要首页还成立 —— 两者各自写自己的特征就行。
   （这条在"进竞技场"这个例子上看不出来，因为它本来就是替换式的关系。）
2. **每个记录信息的状态都必须有流程节点认领**（节点的 ``page`` 写它），
   否则 ``Scenario.validate()`` 直接报错：重定位到那个状态之后无处可去。
   分类节点和叠加层没有这个要求。

## `home`（首页）为什么在**功能**目录里

它原来在游戏级的 ``games/mingjiangsha/pages.py``，用竞技卡当识别特征。
那是错的：竞技卡是竞技功能的专属入口图（首页上还有「房间 / 战没 / 煮酒」
三张并列的兄弟卡，各属各自的功能），拿它定义"游戏级的首页"等于把首页的
身份绑在竞技功能上 —— 别的功能为了认首页，得反过来引用竞技场的资源。

所以首页跟着它那张卡一起下移到这里。**代价是每个功能都声明自己的 `home`**，
换来的是功能之间零依赖。等真有第二个功能、两边的首页特征确实一样时，再用
底部导航栏那种共用 UI 把首页提回游戏级（候选和实测分数见
:mod:`games.mingjiangsha.pages`）。

## 这个父节点暂时不是 group

按规矩，父节点应该一律 ``kind: group``（纯分类、不参与匹配）。但这里
``home`` **自己记录信息**（"我在首页"），所以它有 ``queries``、是个普通页面。

要把它改成分类节点，得先把"首页"建成 ``home/lobby`` 这样的**状态节点**
（``home`` 只当分类容器）—— 那是加"匹配中 / 选将 / 结算"这些状态时该做的事，
现在只有两个状态，改了反而多一层。**加新状态时顺手做掉这件事。**
"""

from __future__ import annotations

from gamebot.atomic.query import ImageQuery
from gamebot.state import Page
from gamebot.types import Region

from ..shortcuts import CONF_JINGJI, JINGJI_ROI, T_JINGJI

#: 页面标识的搜索区域（客户区坐标）：左上角那一块。
#: 刻意避开中间的「巅峰竞技场」横幅 —— 它也含"竞技场"三个字。
#: 页面标识：左上角「竞技场」标题。
#: **它是页面身份，不是某个步骤的图** —— 所以放这儿，不放 steps/。
T_TITLE = "jingji/title.png"

JINGJI_PAGE_ROI = Region(40, 0, 240, 90)

#: 页面标识的阈值。实测三种状态都是 1.000，给 0.90 很宽裕。
CONF_TITLE = 0.90

FEATURE_PAGES: list[tuple[Page, str | None]] = [
    (
        Page(
            "home",
            name="首页",
            min_stable_frames=2,  # 进首页时那排卡有个滑入动画，等它停稳
            roi=JINGJI_ROI,
            queries=(
                # region 显式给上：页面树定位用它、直接跑 Query 时也用它
                ImageQuery(T_JINGJI, region=JINGJI_ROI, confidence=CONF_JINGJI),
            ),
            description="主界面：中间一排模式卡（竞技 / 房间 / 战没 / 煮酒）",
        ),
        None,
    ),
    (
        Page(
            "home/jingji",
            name="竞技场",
            roi=JINGJI_PAGE_ROI,
            queries=(
                # region 显式给上：页面树定位用它，直接跑 Query 时也用它，
                # 两条路径都成立（页面 roi 只对前者生效）。
                ImageQuery(T_TITLE, region=JINGJI_PAGE_ROI, confidence=CONF_TITLE),
            ),
            description="竞技场：三张图对应它的三种状态（建队前/建队后/已准备）",
        ),
        "home",
    ),
]
