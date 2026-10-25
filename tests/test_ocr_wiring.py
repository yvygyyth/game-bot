"""OCR 的**接线** —— 装了包就该真的用上，没装要说清为什么。

## 这条回归钉的是什么

早先 ``bootstrap.build_reader`` **永远**返回 ``UnavailableTextReader``，
于是 ``find_text`` / ``read_text`` / ``read_number`` 不管装没装 OCR 都是
``not_found``。``vision/ocr.py`` 里两个实现写了却从来没被接上 ——
"代码在、路不通"，而且表现和"画面上真没有那行字"一模一样，极难查。

所以这里测的是**选择逻辑**（用注入的探测函数，不依赖跑测试那台机器装了什么），
以及"没装时退化得明白"。
"""

from __future__ import annotations

from gamebot.atomic.vision import UnavailableTextReader
from gamebot.bootstrap import build_reader, choose_ocr_engine


class TestChooseOcrEngine:
    def test_prefers_rapidocr(self) -> None:
        """两个都装了选 RapidOCR：纯 pip 包（模型自带），不用额外装 exe。"""
        both = {"rapidocr_onnxruntime", "pytesseract"}
        assert choose_ocr_engine(lambda name: name in both) == "rapid"

    def test_falls_back_to_tesseract(self) -> None:
        assert choose_ocr_engine(lambda name: name == "pytesseract") == "tesseract"

    def test_none_when_nothing_installed(self) -> None:
        assert choose_ocr_engine(lambda name: False) is None


class TestBuildReader:
    def test_none_engine_degrades_with_a_reason(self) -> None:
        reader = build_reader(engine="none")
        assert isinstance(reader, UnavailableTextReader)
        assert "OCR" in reader.reason

    def test_explicit_rapid_builds_the_real_reader(self) -> None:
        from gamebot.vision.ocr import RapidOcrReader

        assert isinstance(build_reader(engine="rapid"), RapidOcrReader)

    def test_explicit_tesseract_builds_the_real_reader(self) -> None:
        from gamebot.vision.ocr import TesseractReader

        assert isinstance(build_reader(engine="tesseract"), TesseractReader)

    def test_unknown_engine_degrades_instead_of_crashing(self) -> None:
        """拼错引擎名不该让整个脚本起不来 —— 但也不能悄悄换一个。"""
        assert isinstance(build_reader(engine="rapd"), UnavailableTextReader)
