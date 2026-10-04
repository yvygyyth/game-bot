"""原子化方法层（L0 ~ L5）—— 47 个原子方法。

层次与依赖（**只能向下依赖，不能反向**）::

    L5 actions      ── 依赖 Session + 输入后端
    L4 combinators  ── 依赖 Frame + Query +（wait_* 才依赖）Session
    L3 query        ── 只依赖 Frame 的方法签名（不依赖实现）
    L2 frame        ── 依赖 Session（数据来源）+ Matcher/TextReader 协议
    L1 session      ── 依赖 ScreenBackend / InputBackend
    L0 types        ── 无依赖

清单（详见 docs/atomic-inventory.md）::

    L1 截图       3   Session.capture / capture_region / get_screen_size
    L2 Frame 查询 12  find_image / find_all_images / find_text / find_all_texts /
                      read_text / read_number / get_pixel / compare_region /
                      is_image_visible / crop / to_numpy / save
    L3 Query      11  ImageQuery / AllImagesQuery / TextQuery / AllTextsQuery /
                      NumberQuery / PixelQuery / CompareQuery / VisibleQuery /
                      AndQuery / OrQuery / NotQuery
    L4 组合子     10  find_all_of / find_any_of / find_first_of / find_none_of /
                      count_hits / wait_any_of / wait_all_of / wait_until /
                      wait_stable / wait_disappear
    L5 动作       13  click_point / click_image / click_text / double_click /
                      right_click / move_to / drag / drag_image / scroll /
                      type_text / press_key / hotkey / sleep

注：设计稿里 L3 是 9 个（没有 AllTextsQuery / VisibleQuery）。这里补了两个，
因为 ``find_all_texts``（L2 有）没有对应的 Query 描述符会很难配置化，
而"不可见即有效答案"和"找不到即失败"是两种语义，混用会写出 bug。
"""

from __future__ import annotations

from . import actions, combinators, frame, query, session, vision
from .backends.base import BackendBundle, InputBackend, ScreenBackend, WindowBackend, WindowInfo
from .frame import Frame
from .query import (
    AllImagesQuery,
    AllTextsQuery,
    AndQuery,
    CompareQuery,
    ImageQuery,
    NotQuery,
    NumberQuery,
    OrQuery,
    PixelQuery,
    Query,
    TextQuery,
    VisibleQuery,
)
from .session import BaseSession, CoordinateMapper, Session, build_session
from .vision import Matcher, MatchResult, TextBox, TextReader, UnavailableTextReader

__all__ = [  # noqa: RUF022 - 按层次分组比字母序有用，别改成字典序
    # L0
    # L1
    "BaseSession",
    "BackendBundle",
    "CoordinateMapper",
    "InputBackend",
    "MatchResult",
    "Matcher",
    "ScreenBackend",
    "Session",
    "TextBox",
    "TextReader",
    "UnavailableTextReader",
    "WindowBackend",
    "WindowInfo",
    "build_session",
    # L2
    "Frame",
    # L3
    "AllImagesQuery",
    "AllTextsQuery",
    "AndQuery",
    "CompareQuery",
    "ImageQuery",
    "NotQuery",
    "NumberQuery",
    "OrQuery",
    "PixelQuery",
    "Query",
    "TextQuery",
    "VisibleQuery",
    # 子模块（函数族入口）
    "actions",
    "combinators",
    "frame",
    "query",
    "session",
    "vision",
]
