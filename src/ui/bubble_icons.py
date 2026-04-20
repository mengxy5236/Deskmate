"""
图标模块：从 image.png 加载星形图标，按尺寸缩放缓存
"""
from pathlib import Path
from PyQt6.QtCore import Qt, QRect
from PyQt6.QtGui import QPixmap


_icon_cache: dict[int, QPixmap] = {}
_icon_source = Path(__file__).parent.parent / "asset" / "image.png"


def get_icon(size: int = 48) -> QPixmap:
    if size not in _icon_cache:
        src = QPixmap(str(_icon_source))
        sw, sh = src.width(), src.height()

        # 截取中间区域（去掉左右白边/文字部分）
        margin = int(sw * 0.20)
        crop_rect = QRect(margin, 0, sw - margin * 2, sh)

        cropped = src.copy(crop_rect)
        _icon_cache[size] = cropped.scaled(
            size, size,
            Qt.AspectRatioMode.KeepAspectRatio,
            Qt.TransformationMode.SmoothTransformation,
        )
    return _icon_cache[size]
