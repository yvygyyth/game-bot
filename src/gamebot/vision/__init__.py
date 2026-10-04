"""视觉算法实现 —— ``Matcher`` / ``TextReader`` 协议的具体实现放这里。

为什么单独一个包：

* 这些实现依赖 opencv / onnxruntime / tesseract，属于"重且可选"的依赖，
  不能塞进 ``atomic`` 让整个框架被它们绑架；
* 换匹配算法（模板匹配 -> 特征点 -> 神经网络）时，只动这个包，
  ``Frame`` 的 12 个查询方法一行都不用改；
* 算法参数（金字塔层数、NMS 阈值）在这里收口，不散到业务脚本里。

和 ``atomic/vision.py`` 的分工：

* ``atomic/vision.py`` 定义**协议和返回值**（``Matcher`` / ``MatchResult``）
* 本包提供**实现**（``OpenCvMatcher`` / ``RapidOcrReader``）
"""

from __future__ import annotations

__all__: list[str] = []
