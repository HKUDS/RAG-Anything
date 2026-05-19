"""Tests for Chinese CID font registration (issue #24).

Verifies that STSong-Light is registered as the cross-platform Chinese CID
font instead of invalid system font names like SimSun/SimHei.
"""

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent))


class TestChineseCIDFont:
    """Test CID font registration for Chinese text rendering."""

    def test_stsong_light_is_valid_cid_font(self):
        """STSong-Light should register successfully as a CID font."""
        from reportlab.pdfbase.cidfonts import UnicodeCIDFont
        from reportlab.pdfbase import pdfmetrics

        font = UnicodeCIDFont("STSong-Light")
        pdfmetrics.registerFont(font)
        # No exception means it worked

    def test_invalid_cid_font_names_raise(self):
        """Font names used in the old code should fail as CID fonts."""
        from reportlab.pdfbase.cidfonts import UnicodeCIDFont

        invalid_names = ["SimSun", "SimHei", "Microsoft YaHei", "STHeiti"]
        for name in invalid_names:
            with pytest.raises(Exception):
                UnicodeCIDFont(name)

    def test_all_valid_cid_cjk_font_names(self):
        """Verify the set of valid CJK CID font names in reportlab."""
        from reportlab.pdfbase.cidfonts import UnicodeCIDFont
        from reportlab.pdfbase import pdfmetrics

        valid_cjk = [
            "STSong-Light",
            "MSung-Light",
            "HeiseiMin-W3",
            "HeiseiKakuGo-W5",
            "HYSMyeongJo-Medium",
        ]
        for name in valid_cjk:
            font = UnicodeCIDFont(name)
            pdfmetrics.registerFont(font)
