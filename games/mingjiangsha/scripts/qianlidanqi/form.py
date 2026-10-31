"""千里单骑 —— 运行参数表单。

只有一个参数：**要选的武将**（默认吕布）。
选将步骤把它填进搜索框，再点搜索结果的第一张卡。
"""

from __future__ import annotations

from gamebot.params import FieldKind, FormSpec, ParamField

__all__ = ["FORM", "WUJIANG_PARAM"]

#: "要选的武将"的参数名。
WUJIANG_PARAM = "qianlidanqi.wu_jiang"

FORM = FormSpec(
    title="千里单骑参数",
    fields=(
        ParamField(
            WUJIANG_PARAM,
            FieldKind.TEXT,
            "吕布",
            label="要选的武将",
            help="默认吕布。会填进选将面板的搜索框，点搜索结果的第一张卡。",
        ),
    ),
)
