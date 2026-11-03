"""每日领奖 —— 模板路径。"""

from __future__ import annotations

__all__ = [
    "T_ACTIVITY_ENTRY",
    "T_ACTIVITY_STATE",
    "T_GALLERY_ENTRY",
    "T_GALLERY_GIFT",
    "T_GALLERY_STATE",
    "T_HOME",
    "T_MAIL_ENTRY",
    "T_MAIL_ONE_CLICK",
    "T_MAIL_STATE",
]

# ---- 首页入口 ----
T_HOME = "entry/home.png"
T_MAIL_ENTRY = "entry/mail.png"
T_ACTIVITY_ENTRY = "entry/activity.png"
T_GALLERY_ENTRY = "entry/gallery.png"

# ---- 状态锚点 ----
T_MAIL_STATE = "state_mail.png"
T_ACTIVITY_STATE = "state_activity.png"
T_GALLERY_STATE = "state_gallery.png"

# ---- 按钮 ----
T_MAIL_ONE_CLICK = "mail_one_click.png"
T_GALLERY_GIFT = "gallery_gift.png"
