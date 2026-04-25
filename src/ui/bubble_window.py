"""
Deskmate 气泡助手 —— 微信式对话架构

架构说明：
  - 全屏透明画布：showMaximized() + WA_TranslucentBackground
  - 穿透：默认 WindowTransparentForInput，仅星星区域恢复交互
  - InputPanel：内嵌聊天消息列表，用户消息靠右，AI回复靠左
  - 流式：StreamingWorker 驱动打字机效果，文字追加到固定气泡中
  - 主题：支持多套气泡颜色主题，右键菜单切换
  - 渐隐：只显示最近 5 对话对，超出自动删除；旧消息按比例衰减透明度
"""
from __future__ import annotations

import asyncio
import sys
from PyQt6.QtCore import (
    Qt, QThread, QTimer, pyqtSignal, QPoint, QRect,
)
from PyQt6.QtGui import (
    QIcon, QPixmap, QPainter, QColor, QFont, QFontMetrics,
    QMouseEvent, QPainterPath, QCursor,
)
from PyQt6.QtWidgets import (
    QApplication, QWidget, QLabel, QLineEdit, QPushButton,
    QGraphicsDropShadowEffect, QGraphicsOpacityEffect,
    QMenu, QSystemTrayIcon, QGridLayout,
    QScrollArea, QVBoxLayout, QHBoxLayout,
    QFrame, QSizePolicy,
)

from src.core.chat_backend import ChatBackend
from src.ui.cat_animation import CatAnimation


# ═══════════════════════════════════════════════════════════════════════════════
# 主题颜色定义
# ═══════════════════════════════════════════════════════════════════════════════

THEMES = [
    ("#484848", "#2C2C2E"),
    ("#6366F1", "#8B5CF6"),
    ("#3B82F6", "#10B981"),
    ("#6366F1", "#EC4899"),
    ("#8B5CF6", "#F59E0B"),
    ("#14B8A6", "#6366F1"),
    ("#F97316", "#8B5CF6"),
    ("#EC4899", "#3B82F6"),
    ("#10B981", "#F59E0B"),
    ("#6366F1", "#14B8A6"),
    ("#8B5CF6", "#EC4899"),
    ("#3B82F6", "#F97316"),
    ("#F59E0B", "#10B981"),
    ("#14B8A6", "#EC4899"),
    ("#6366F1", "#F59E0B"),
    ("#8B5CF6", "#3B82F6"),
    ("#EC4899", "#14B8A6"),
    ("#10B981", "#6366F1"),
    ("#F97316", "#EC4899"),
    ("#3B82F6", "#8B5CF6"),
    ("#F59E0B", "#6366F1"),
    ("#14B8A6", "#F97316"),
    ("#6366F1", "#10B981"),
    ("#8B5CF6", "#14B8A6"),
    ("#EC4899", "#F59E0B"),
    ("#3B82F6", "#6366F1"),
    ("#10B981", "#EC4899"),
    ("#F97316", "#3B82F6"),
    ("#6366F1", "#F97316"),
    ("#8B5CF6", "#10B981"),
    ("#F59E0B", "#8B5CF6"),
    ("#14B8A6", "#6366F1"),
    ("#EC4899", "#8B5CF6"),
    ("#3B82F6", "#14B8A6"),
    ("#6366F1", "#EC4899"),
    ("#10B981", "#F59E0B"),
    ("#8B5CF6", "#F97316"),
    ("#F59E0B", "#EC4899"),
    ("#14B8A6", "#3B82F6"),
    ("#EC4899", "#6366F1"),
    ("#6366F1", "#3B82F6"),
]


def _hex_to_rgb(hex_str: str) -> tuple[int, int, int]:
    h = hex_str.lstrip('#')
    return tuple(int(h[i:i+2], 16) for i in (0, 2, 4))


def _best_text_color(bg_hex: str) -> str:
    """根据背景色返回浅色或深色文字。"""
    r, g, b = _hex_to_rgb(bg_hex)
    luminance = 0.299 * r + 0.587 * g + 0.114 * b
    return "#FFFFFF" if luminance < 128 else "#1A1A1A"


# ═══════════════════════════════════════════════════════════════════════════════
# 流式 Worker（逐字发射信号，实现打字机效果）
# ═══════════════════════════════════════════════════════════════════════════════

class StreamingWorker(QThread):
    chunk = pyqtSignal(str)
    done = pyqtSignal(str)
    error = pyqtSignal(str)

    def __init__(self, backend: ChatBackend, prompt: str, session_id: int) -> None:
        super().__init__()
        self._backend = backend
        self._prompt = prompt
        self._session_id = session_id

    def run(self) -> None:
        try:
            loop = asyncio.new_event_loop()
            asyncio.set_event_loop(loop)
            try:
                loop.run_until_complete(self._consume())
            finally:
                loop.close()
        except Exception as exc:
            self.error.emit(str(exc))

    async def _consume(self) -> None:
        full = ""
        async for token in self._backend.send_message_stream(self._prompt, self._session_id):
            full += token
            self.chunk.emit(token)
        self.done.emit(full)


# ═══════════════════════════════════════════════════════════════════════════════
# 设置面板（主题选择）
# ═══════════════════════════════════════════════════════════════════════════════

class ThemeColorButton(QPushButton):

    clicked = pyqtSignal(str, bool)

    def __init__(self, color: str, is_user: bool, parent=None) -> None:
        super().__init__(parent)
        self._color = color
        self._is_user = is_user
        self.setFixedSize(36, 36)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self._apply_style(False)

    def _apply_style(self, selected: bool) -> None:
        border = "3px solid #60A5FA" if selected else "2px solid rgba(255,255,255,0.2)"
        self.setStyleSheet(
            f"QPushButton {{"
            f"  background: {self._color};"
            f"  border: {border};"
            f"  border-radius: 8px;"
            f"}}"
        )

    def set_selected(self, selected: bool) -> None:
        self._apply_style(selected)


class SettingsPanel(QWidget):

    COLS = 4
    theme_changed = pyqtSignal(str, str)

    def __init__(self, parent: QWidget) -> None:
        super().__init__(parent)
        self._parent_window = parent
        self._selected_user = THEMES[0][0]
        self._selected_assistant = THEMES[0][1]
        self._user_buttons: list[ThemeColorButton] = []
        self._assistant_buttons: list[ThemeColorButton] = []
        self._build_ui()

    def _build_ui(self) -> None:
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        self.setWindowFlags(
            Qt.WindowType.FramelessWindowHint
            | Qt.WindowType.Tool,
        )
        self.setFixedWidth(280)

        main_layout = QVBoxLayout(self)
        main_layout.setContentsMargins(12, 12, 12, 12)
        main_layout.setSpacing(8)

        title = QLabel("主题设置")
        title.setFont(QFont("Microsoft YaHei UI", 13, QFont.Weight.Bold))
        title.setStyleSheet("QLabel { color: #F1F5F9; background: transparent; }")
        main_layout.addWidget(title)

        separator = QFrame()
        separator.setFrameShape(QFrame.Shape.HLine)
        separator.setStyleSheet("QFrame { background: rgba(255,255,255,0.1); border: none; }")
        main_layout.addWidget(separator)

        user_label = QLabel("用户气泡颜色")
        user_label.setFont(QFont("Microsoft YaHei UI", 11))
        user_label.setStyleSheet("QLabel { color: #94A3B8; background: transparent; }")
        main_layout.addWidget(user_label)

        user_grid = QGridLayout()
        user_grid.setSpacing(6)
        for i, (_, assistant) in enumerate(THEMES):
            btn = ThemeColorButton(assistant, True, self)
            btn.clicked.connect(lambda c, is_u=True: self._on_color_clicked(c, True))
            self._assistant_buttons.append(btn)
            row, col = divmod(i, self.COLS)
            user_grid.addWidget(btn, row, col)
        main_layout.addLayout(user_grid)

        assistant_label = QLabel("AI 气泡颜色")
        assistant_label.setFont(QFont("Microsoft YaHei UI", 11))
        assistant_label.setStyleSheet("QLabel { color: #94A3B8; background: transparent; }")
        main_layout.addWidget(assistant_label)

        assistant_grid = QGridLayout()
        assistant_grid.setSpacing(6)
        for i, (user, _) in enumerate(THEMES):
            btn = ThemeColorButton(user, False, self)
            btn.clicked.connect(lambda c, is_u=False: self._on_color_clicked(c, False))
            self._user_buttons.append(btn)
            row, col = divmod(i, self.COLS)
            assistant_grid.addWidget(btn, row, col)
        main_layout.addLayout(assistant_grid)

        main_layout.addStretch(1)

        self._update_button_states()

        self.setStyleSheet("QWidget { background: rgba(20, 24, 40, 0.95); }")

    def _update_button_states(self) -> None:
        for btn in self._user_buttons:
            btn.set_selected(btn._color == self._selected_user)
        for btn in self._assistant_buttons:
            btn.set_selected(btn._color == self._selected_assistant)

    def _on_color_clicked(self, color: str, is_user: bool) -> None:
        if is_user:
            self._selected_user = color
        else:
            self._selected_assistant = color
        self._update_button_states()
        self.theme_changed.emit(self._selected_user, self._selected_assistant)

    def show_at_star(self, star_geometry: QRect) -> None:
        x = star_geometry.right() + 10
        screen = QApplication.primaryScreen().availableGeometry()
        if x + self.width() > screen.right():
            x = star_geometry.left() - self.width() - 10
        y = star_geometry.top()
        if y + self.height() > screen.bottom():
            y = screen.bottom() - self.height() - 10
        self.move(int(x), int(y))
        self.show()
        self.activateWindow()

    def hide_panel(self) -> None:
        self.hide()


# ═══════════════════════════════════════════════════════════════════════════════
# 四角星按钮
# ═══════════════════════════════════════════════════════════════════════════════

class StarButton(QWidget):
    clicked = pyqtSignal()
    double_clicked = pyqtSignal()
    drag_delta = pyqtSignal(QPoint)

    ICON_SIZE = 64

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.setFixedSize(self.ICON_SIZE, self.ICON_SIZE)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self._dragging = False
        self._drag_start = QPoint()
        self._moved_during_press = False
        self._click_timer = QTimer(self)
        self._click_timer.setSingleShot(True)
        self._click_timer.setInterval(250)
        self._click_timer.timeout.connect(self._on_single_click)

        self._cat_animation = CatAnimation(self.ICON_SIZE)
        self._cat_animation._timer.timeout.connect(self.update)

        self._normal_state = 'idle'

        self._angry_timer = QTimer(self)
        self._angry_timer.setSingleShot(True)
        self._angry_timer.timeout.connect(self._restore_normal_state)

    def paintEvent(self, e) -> None:
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform)
        current_frame = self._cat_animation.get_current_frame()
        painter.drawPixmap(self.rect(), current_frame)

    def mousePressEvent(self, e: QMouseEvent) -> None:
        if e.button() == Qt.MouseButton.LeftButton:
            self._dragging = True
            self._drag_start = e.globalPosition().toPoint()
            self._moved_during_press = False
            e.accept()
        elif e.button() == Qt.MouseButton.RightButton:
            e.ignore()
        else:
            e.ignore()

    def mouseMoveEvent(self, e: QMouseEvent) -> None:
        if not self._dragging:
            return
        if not (e.buttons() & Qt.MouseButton.LeftButton):
            self._dragging = False
            return
        self._moved_during_press = True
        delta = e.globalPosition().toPoint() - self._drag_start
        self._drag_start = e.globalPosition().toPoint()
        self.drag_delta.emit(delta)
        e.accept()

    def mouseReleaseEvent(self, e: QMouseEvent) -> None:
        if e.button() == Qt.MouseButton.LeftButton:
            if not self._moved_during_press:
                self._click_timer.start()
            else:
                self.clicked.emit()
            e.accept()
        self._dragging = False

    def mouseDoubleClickEvent(self, e: QMouseEvent) -> None:
        if e.button() == Qt.MouseButton.LeftButton:
            self._click_timer.stop()
            self.double_clicked.emit()
            e.accept()

    def _on_single_click(self):
        if self._cat_animation.current_state not in ['angry', 'walkingright', 'walkingleft']:
            self._normal_state = self._cat_animation.current_state
        self._cat_animation.play('angry')
        self._angry_timer.start(500)
        self.clicked.emit()

    def _restore_normal_state(self):
        self._cat_animation.play(self._normal_state)

    def set_animation_state(self, state: str):
        self._normal_state = state
        self._cat_animation.play(state)


# ═══════════════════════════════════════════════════════════════════════════════
# 聊天气泡
# ═══════════════════════════════════════════════════════════════════════════════

class ChatBubble(QFrame):

    MAX_W = 220
    MIN_H = 28

    def __init__(self, text: str, role: str, opacity_factor: float = 1.0,
                 theme_user: str = "#ED723F", theme_assistant: str = "#215A59",
                 parent=None) -> None:
        super().__init__(parent)
        self._role = role
        self._text = text
        self._theme_user = theme_user
        self._theme_assistant = theme_assistant
        self.setFrameShape(QFrame.Shape.NoFrame)
        self.setMinimumHeight(self.MIN_H)
        self.setMaximumWidth(self.MAX_W)
        self.setSizePolicy(QSizePolicy.Policy.Maximum, QSizePolicy.Policy.Minimum)

        self._label = QLabel(text, self)
        self._label.setFont(QFont("Microsoft YaHei UI", 12))
        self._label.setWordWrap(True)
        self._label.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        self._label.setMaximumWidth(self.MAX_W - 20)

        shadow = QGraphicsDropShadowEffect(self)
        shadow.setBlurRadius(12)
        shadow.setColor(QColor(0, 0, 0, 40))
        shadow.setOffset(0, 2)
        self.setGraphicsEffect(shadow)

        layout = QHBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)
        if role == "user":
            layout.addStretch(1)
            layout.addWidget(self._label)
        else:
            layout.addWidget(self._label)
            layout.addStretch(1)

        self._apply_theme()
        self.set_opacity(opacity_factor)

    def _apply_theme(self) -> None:
        if self._role == "user":
            bg = self._theme_user
        else:
            bg = self._theme_assistant
        r, g, b = _hex_to_rgb(bg)
        self.setStyleSheet(
            f"QFrame {{"
            f"  background: rgba({r},{g},{b},0.88);"
            f"  border-radius: 18px;"
            f"  padding: 8px 14px;"
            f" }}"
            f"QLabel {{ color: #FFFFFF; background: transparent; }}"
        )

    def set_theme(self, user: str, assistant: str) -> None:
        self._theme_user = user
        self._theme_assistant = assistant
        self._apply_theme()

    def set_opacity(self, factor: float) -> None:
        effect = QGraphicsOpacityEffect(self)
        effect.setOpacity(max(0.0, min(1.0, factor)))
        self.setGraphicsEffect(effect)

    def append_text(self, chunk: str) -> None:
        self._text += chunk
        self._label.setText(self._text)
        self._label.setMaximumWidth(self.MAX_W - 20)
        if self.height() < self.MIN_H:
            self.setMinimumHeight(self.MIN_H)

    @staticmethod
    def estimate_height(text: str, max_w: int) -> int:
        metrics = QFontMetrics(QFont("Microsoft YaHei UI", 12))
        rect = metrics.boundingRect(0, 0, max_w - 20, 0, int(Qt.TextFlag.TextWordWrap), text)
        raw_h = rect.height() + 12
        return max(raw_h, 28)


# ═══════════════════════════════════════════════════════════════════════════════
# 聊天消息列表
# ═══════════════════════════════════════════════════════════════════════════════

class ChatMessageList(QWidget):

    PANEL_W = 300
    MAX_H = 400
    INPUT_H = 34
    MARGIN = 16
    BUBBLE_GAP = 6

    MAX_PAIRS = 5
    _OPACITY_TABLE = [0.05, 0.25, 0.55, 0.75, 1.0]

    def _opacity_for(self, from_newest: int) -> float:
        if from_newest >= self.MAX_PAIRS:
            return -1.0
        return self._OPACITY_TABLE[self.MAX_PAIRS - 1 - from_newest]

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self._messages: list[ChatBubble] = []
        self._pending_bubble: ChatBubble | None = None
        self._batch_timer: QTimer | None = None
        self._pending_chunks: list[str] = []
        self._theme_user = THEMES[0][0]
        self._theme_assistant = THEMES[0][1]
        self._build_ui()

    def set_theme(self, user: str, assistant: str) -> None:
        self._theme_user = user
        self._theme_assistant = assistant
        for m in self._messages:
            m.set_theme(user, assistant)

    def _build_ui(self) -> None:
        self.setFixedWidth(self.PANEL_W)
        self.setMaximumHeight(self.MAX_H)
        self.setMinimumHeight(150)
        self.setSizePolicy(QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Preferred)
        self.setStyleSheet("QWidget { background: transparent; }")

        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(0)

        self._scroll = QScrollArea(self)
        self._scroll.setWidgetResizable(True)
        self._scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self._scroll.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)
        self._scroll.setStyleSheet("""
            QScrollArea {
                background: transparent;
                border: none;
            }
            QScrollBar:vertical {
                background: rgba(255, 255, 255, 0.06);
                width: 6px;
                margin: 0;
                border-radius: 3px;
            }
            QScrollBar::handle:vertical {
                background: rgba(255, 255, 255, 0.25);
                border-radius: 3px;
                min-height: 30px;
            }
            QScrollBar::handle:vertical:hover {
                background: rgba(255, 255, 255, 0.4);
            }
            QScrollBar::handle:vertical:pressed {
                background: rgba(255, 255, 255, 0.55);
            }
            QScrollBar::add-page, QScrollBar::sub-page { background: none; }
        """)

        self._container = QWidget()
        self._container.setStyleSheet("background: transparent;")
        self._container_layout = QVBoxLayout(self._container)
        self._container_layout.setSpacing(self.BUBBLE_GAP)
        self._container_layout.setContentsMargins(0, 0, 0, 0)
        self._container_layout.addStretch(1)

        self._scroll.setWidget(self._container)
        outer.addWidget(self._scroll, 1)

        self._input = QLineEdit(self)
        self._input.setFixedHeight(34)
        self._input.setFont(QFont("Microsoft YaHei UI", 12))
        self._input.setPlaceholderText("Message...")
        self._input.setMaxLength(2000)
        self._input.setStyleSheet("""
            QLineEdit {
                background: #3A3A3C;
                border: none;
                border-radius: 18px;
                color: #FFFFFF;
                padding: 8px 18px;
                font-size: 14px;
                selection-background-color: rgba(0, 122, 255, 0.4);
            }
            QLineEdit:hover {
                background: #48484A;
            }
            QLineEdit:focus {
                background: #3A3A3C;
            }
            QLineEdit::placeholder { color: #8E8E93; }
        """)
        self._input.setAttribute(Qt.WidgetAttribute.WA_MacShowFocusRect, False)
        outer.addWidget(self._input)

    def _refresh_opacities(self) -> None:
        total = len(self._messages)
        to_delete: list[tuple[int, ChatBubble]] = []

        for i, bubble in enumerate(self._messages):
            from_newest = total - 1 - i
            opacity = self._opacity_for(from_newest)
            if opacity < 0:
                to_delete.append((i, bubble))
            else:
                bubble.set_opacity(opacity)

        for row_idx, bubble in reversed(to_delete):
            self._remove_row(row_idx)
            self._messages.remove(bubble)
            bubble.deleteLater()

    def _remove_row(self, layout_index: int) -> None:
        item = self._container_layout.takeAt(layout_index)
        if item.layout():
            for j in range(item.layout().count()):
                child = item.layout().itemAt(j)
                if child.widget():
                    child.widget().deleteLater()
            item.layout().deleteLater()
        elif item.widget():
            item.widget().deleteLater()

    def _recompute_and_scroll(self) -> None:
        self._container_layout.activate()
        total_h = self._container.sizeHint().height()
        self._container.setMinimumHeight(total_h)
        self._container.setMaximumHeight(total_h)
        QTimer.singleShot(5, self._scroll_to_bottom)

    def _scroll_to_bottom(self) -> None:
        bar = self._scroll.verticalScrollBar()
        bar.setValue(bar.maximum())

    def add_user_bubble(self, text: str) -> None:
        bubble = ChatBubble(
            text, "user", opacity_factor=1.0,
            theme_user=self._theme_user, theme_assistant=self._theme_assistant,
        )
        self._add_row(bubble)
        self._refresh_opacities()
        self._recompute_and_scroll()

    def add_assistant_bubble(self, text: str = "") -> ChatBubble:
        bubble = ChatBubble(
            text, "assistant", opacity_factor=1.0,
            theme_user=self._theme_user, theme_assistant=self._theme_assistant,
        )
        self._add_row(bubble)
        self._pending_bubble = bubble
        self._refresh_opacities()
        self._recompute_and_scroll()
        return bubble

    def append_to_pending(self, chunk: str) -> None:
        self._pending_chunks.append(chunk)
        if self._pending_bubble is None:
            return
        if self._batch_timer is None:
            self._batch_timer = QTimer(self)
            self._batch_timer.setSingleShot(True)
            self._batch_timer.timeout.connect(self._flush_chunks)
        if not self._batch_timer.isActive():
            self._batch_timer.start(30)

    def _flush_chunks(self) -> None:
        if not self._pending_bubble:
            self._pending_chunks.clear()
            return
        joined = "".join(self._pending_chunks)
        self._pending_chunks.clear()
        self._pending_bubble.append_text(joined)
        self._recompute_and_scroll()

    def finalize_pending(self) -> None:
        if self._pending_chunks and self._pending_bubble:
            joined = "".join(self._pending_chunks)
            self._pending_chunks.clear()
            self._pending_bubble.append_text(joined)
        self._pending_bubble = None
        self._recompute_and_scroll()

    def clear_messages(self) -> None:
        self._messages.clear()
        self._pending_bubble = None
        self._pending_chunks.clear()
        while self._container_layout.count() > 1:
            self._remove_row(0)
        self._recompute_and_scroll()

    def _add_row(self, bubble: ChatBubble) -> None:
        row = QHBoxLayout()
        row.setContentsMargins(12, 4, 12, 4)
        row.setSpacing(0)
        if bubble._role == "user":
            row.addStretch(1)
            row.addWidget(bubble, 0, Qt.AlignmentFlag.AlignRight)
        else:
            row.addWidget(bubble, 0, Qt.AlignmentFlag.AlignLeft)
            row.addStretch(1)
        insert_idx = self._container_layout.count() - 1
        self._container_layout.insertLayout(insert_idx, row)
        self._messages.append(bubble)


# ═══════════════════════════════════════════════════════════════════════════════
# 输入面板（含消息列表 + 固定底部输入框）
# ═══════════════════════════════════════════════════════════════════════════════

class ResizeGrip(QWidget):

    resize_drag = pyqtSignal(int, int)

    SIZE = 18

    def __init__(self, parent: QWidget) -> None:
        super().__init__(parent)
        self.setFixedSize(self.SIZE, self.SIZE)
        self.setCursor(Qt.CursorShape.SizeFDiagCursor)
        self._dragging = False

    def paintEvent(self, e) -> None:
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        painter.setPen(QColor(255, 255, 255, 100))
        painter.setBrush(QColor(255, 255, 255, 40))
        w, h = self.width(), self.height()
        path = QPainterPath()
        path.moveTo(2, h - 2)
        path.lineTo(w - 2, h - 2)
        path.lineTo(w - 2, 2)
        path.closeSubpath()
        painter.drawPath(path)

    def mousePressEvent(self, e: QMouseEvent) -> None:
        if e.button() == Qt.MouseButton.LeftButton:
            self._dragging = True
            self._start = e.globalPosition().toPoint()
            e.accept()

    def mouseMoveEvent(self, e: QMouseEvent) -> None:
        if self._dragging and (e.buttons() & Qt.MouseButton.LeftButton):
            delta = e.globalPosition().toPoint() - self._start
            self._start = e.globalPosition().toPoint()
            self.resize_drag.emit(delta.x(), delta.y())
            e.accept()

    def mouseReleaseEvent(self, e: QMouseEvent) -> None:
        self._dragging = False


class InputPanel(QWidget):

    send_clicked = pyqtSignal(str)
    MIN_PANEL_W = 200
    MAX_PANEL_W = 600
    MIN_PANEL_H = 150
    MAX_PANEL_H = 400
    _panel_w = 300
    _panel_h = 200

    def __init__(self, parent: QWidget) -> None:
        super().__init__(parent)
        self._parent_window = parent
        self._resizing = False
        self._panel_h = 200
        self._build_ui()

    def _build_ui(self) -> None:
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        self.setWindowFlags(
            Qt.WindowType.FramelessWindowHint
            | Qt.WindowType.Tool,
        )
        self.setStyleSheet("QWidget { border: none; }")

        self._vbox = QVBoxLayout(self)
        self._vbox.setContentsMargins(0, 0, 0, 0)
        self._vbox.setSpacing(0)
        self._msg_list = ChatMessageList(self)
        self._vbox.addWidget(self._msg_list)

        self._resize_grip = ResizeGrip(self)
        self._resize_grip.move(self._panel_w - ResizeGrip.SIZE, self._panel_h - ResizeGrip.SIZE)
        self._resize_grip.resize_drag.connect(self._on_resize_drag)

        self._msg_list._input.returnPressed.connect(self._on_send)
        self._msg_list._input.installEventFilter(self)

    def paintEvent(self, event) -> None:
        pass

    def _compute_final_pos(self) -> QPoint:
        star_rect = self._parent_window._star_geometry()
        panel_w = self._panel_w
        x = star_rect.left() - panel_w - 10
        h = self._msg_list.height() + 4
        y = star_rect.top() - h
        if y < 10:
            y = star_rect.bottom() + 10
        return QPoint(int(x), int(y))

    def show_input(self) -> None:
        self._msg_list._recompute_and_scroll()
        self._panel_h = min(self._msg_list.height(), ChatMessageList.MAX_H + 4)
        self.resize(self._panel_w, self._panel_h)
        self.move(self._compute_final_pos())
        self._position_grip()
        self.show()
        self._msg_list._input.setFocus()

    def hide_input(self) -> None:
        self.hide()
        self._msg_list._input.clear()

    def follow_star(self) -> None:
        if self.isVisible():
            self.move(self._compute_final_pos())

    def _position_grip(self) -> None:
        self._resize_grip.move(self._panel_w - ResizeGrip.SIZE, self._panel_h - ResizeGrip.SIZE)

    def _on_resize_drag(self, dx: int, dy: int) -> None:
        new_w = max(self.MIN_PANEL_W, min(self.MAX_PANEL_W, self._panel_w + dx))
        new_h = max(self.MIN_PANEL_H, min(self.MAX_PANEL_H, self._panel_h + dy))
        self._panel_w = new_w
        self._panel_h = new_h
        self._msg_list.setFixedWidth(new_w)
        self.resize(new_w, new_h)
        self._position_grip()

    def _on_send(self) -> None:
        text = self._msg_list._input.text().strip()
        if not text:
            return
        self._msg_list._input.clear()
        self.send_clicked.emit(text)

    def eventFilter(self, watched, event) -> None:
        from PyQt6.QtCore import QEvent
        if event.type() == QEvent.Type.KeyPress:
            if event.key() == Qt.Key.Key_Escape:
                self._parent_window._on_input_cancel()
                return
        return super().eventFilter(watched, event)


# ═══════════════════════════════════════════════════════════════════════════════
# 主窗口（全屏透明画布 + 星星区域穿透交互）
# ═══════════════════════════════════════════════════════════════════════════════

class BubbleWindow(QWidget):
    MARGIN = 24
    _ICON_SIZE = 64

    def __init__(self) -> None:
        super().__init__()

        self._backend = ChatBackend()
        self._session_id: int | None = None
        self._stream_worker: StreamingWorker | None = None
        self._current_theme_idx = 0

        self._state = "rest"

        self._setup_window()
        self._build_star_button()
        self._build_input()
        self._build_settings_panel()
        self._setup_tray()

    def _setup_window(self) -> None:
        screen = QApplication.primaryScreen().availableGeometry()
        self.setGeometry(screen)
        self.setWindowFlags(
            Qt.WindowType.FramelessWindowHint
            | Qt.WindowType.WindowStaysOnTopHint
            | Qt.WindowType.Tool,
        )
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        self.setAttribute(Qt.WidgetAttribute.WA_NoSystemBackground)

    def _star_geometry(self) -> QRect:
        return QRect(
            self._star.pos().x(),
            self._star.pos().y(),
            self._ICON_SIZE,
            self._ICON_SIZE,
        )

    def _move_star(self, delta: QPoint) -> None:
        new_x = self._star.x() + delta.x()
        new_y = self._star.y() + delta.y()
        self._star.move(int(new_x), int(new_y))
        if delta.x() > 0:
            self._star.set_animation_state('walkingright')
        elif delta.x() < 0:
            self._star.set_animation_state('walkingleft')
        if self._state == "active" and self._input.isVisible():
            self._input.follow_star()

    def _build_star_button(self) -> None:
        self._star = StarButton(self)
        sg = QApplication.primaryScreen().availableGeometry()
        init_x = sg.right() - self._ICON_SIZE - self.MARGIN
        init_y = sg.bottom() - self._ICON_SIZE - self.MARGIN
        self._star.move(int(init_x), int(init_y))

        glow = QGraphicsDropShadowEffect(self._star)
        glow.setBlurRadius(24)
        glow.setColor(QColor(14, 165, 233, 100))
        glow.setOffset(0, 3)
        self._star.setGraphicsEffect(glow)

        self._star.clicked.connect(self._on_star_clicked)
        self._star.double_clicked.connect(self._on_star_double_clicked)
        self._star.drag_delta.connect(self._move_star)

        self._star.set_animation_state('sleeping')

    def _on_star_double_clicked(self) -> None:
        if self._state == "rest":
            self._activate_input()
        else:
            self._on_input_cancel()

    def _build_input(self) -> None:
        self._input = InputPanel(self)
        self._input.hide()
        self._input.send_clicked.connect(self._on_send)

    def _build_settings_panel(self) -> None:
        self._settings_panel = SettingsPanel(self)
        self._settings_panel.hide()
        self._settings_panel.theme_changed.connect(self._on_theme_changed)

    def _setup_tray(self) -> None:
        self._tray = QSystemTrayIcon(self)
        self._tray.setIcon(QIcon(CatAnimation(self._ICON_SIZE).get_current_frame()))
        self._tray.setToolTip("气泡助手")
        menu = QMenu(self)
        menu.addAction("打开", self._show_window)
        menu.addSeparator()
        menu.addAction("换主题", self._show_theme_menu)
        menu.addSeparator()
        menu.addAction("退出", self.close)
        self._tray.setContextMenu(menu)
        self._tray.activated.connect(lambda r: self._show_window() if r else None)
        self._tray.show()

    def _show_theme_menu(self) -> None:
        menu = QMenu("选择主题", self)
        for i, (user, assistant) in enumerate(THEMES):
            user_color = _hex_to_rgb(user)
            assistant_color = _hex_to_rgb(assistant)
            label = f"  用户 #{i+1:02d}   AI #{i+1:02d}"
            action = menu.addAction(label)
            action.setData(i)
            px = QPixmap(14, 14)
            px.fill(QColor(*user_color))
            action.setIcon(QIcon(px))
        menu.addSeparator()
        menu.addAction("取消")
        chosen = menu.exec(QCursor.pos())
        if chosen and chosen.data() is not None:
            idx = chosen.data()
            user, assistant = THEMES[idx]
            self._current_theme_idx = idx
            self._input._msg_list.set_theme(user, assistant)

    def _on_theme_changed(self, user: str, assistant: str) -> None:
        self._input._msg_list.set_theme(user, assistant)

    def _show_window(self) -> None:
        if self._state == "rest":
            self._activate_input()
        else:
            self._on_input_cancel()
        self.activateWindow()
        self.raise_()

    def mousePressEvent(self, e: QMouseEvent) -> None:
        gp = e.globalPosition().toPoint()
        if e.button() == Qt.MouseButton.LeftButton:
            if self._star_geometry().contains(gp):
                self._on_star_clicked()
                return
            return

        if e.button() == Qt.MouseButton.RightButton:
            if self._star_geometry().contains(gp):
                self._show_star_context_menu()
                return
            if self._input.isVisible() and self._input.geometry().contains(self.mapFromGlobal(gp)):
                self._show_theme_menu()
                return

    def _show_star_context_menu(self) -> None:
        menu = QMenu(self)
        menu.setStyleSheet("""
            QMenu {
                background: #1E293B;
                border: 1px solid rgba(99, 102, 241, 0.3);
                border-radius: 10px;
                padding: 8px;
            }
            QMenu::item {
                color: #F1F5F9;
                padding: 10px 24px;
                border-radius: 8px;
                font-family: "Microsoft YaHei UI";
                font-size: 13px;
            }
            QMenu::item:selected {
                background: rgba(99, 102, 241, 0.3);
            }
            QMenu::separator {
                background: rgba(255,255,255,0.1);
                height: 1px;
                margin: 6px 12px;
            }
        """)

        menu.addAction("打开聊天")
        menu.addSeparator()
        menu.addAction("切换主题")
        menu.addSeparator()
        menu.addAction("退出")

        action = menu.exec(QCursor.pos())
        if action:
            text = action.text()
            if text == "打开聊天":
                self._show_window()
            elif text == "切换主题":
                self._show_theme_menu()
            elif text == "退出":
                self.close()
                QApplication.instance().quit()

    def _on_star_clicked(self) -> None:
        if self._state == "active":
            self._star.set_animation_state('idle')
        else:
            self._star.set_animation_state('sleeping')

    def _activate_input(self) -> None:
        self._state = "active"
        self._input.show_input()
        self._star.set_animation_state('idle')

    def _on_input_cancel(self) -> None:
        if self._state != "active":
            return
        self._input.hide_input()
        self._state = "rest"
        self._star.set_animation_state('sleeping')

    def _on_send(self, content: str) -> None:
        if not content:
            return
        if self._session_id is None:
            self._session_id = self._backend.create_session("气泡助手")

        self._input._msg_list.add_user_bubble(content)
        self._input._msg_list.add_assistant_bubble()
        self._call_stream(content)

    def _call_stream(self, content: str) -> None:
        if self._stream_worker and self._stream_worker.isRunning():
            return
        self._stream_worker = StreamingWorker(
            backend=self._backend,
            prompt=content,
            session_id=self._session_id,
        )
        self._stream_worker.chunk.connect(self._on_stream_chunk)
        self._stream_worker.done.connect(self._on_stream_done)
        self._stream_worker.error.connect(self._on_error)
        self._stream_worker.start()

    def _on_stream_chunk(self, chunk: str) -> None:
        self._input._msg_list.append_to_pending(chunk)

    def _on_stream_done(self, full_text: str) -> None:
        self._input._msg_list.finalize_pending()
        self._stream_worker = None

    def _on_error(self, err: str) -> None:
        self._input._msg_list.finalize_pending()
        self._stream_worker = None

    def closeEvent(self, e) -> None:
        self._tray.hide()
        if self._stream_worker and self._stream_worker.isRunning():
            self._stream_worker.quit()
            self._stream_worker.wait(1000)
        e.accept()


def run_app() -> None:
    app = QApplication([])
    app.setQuitOnLastWindowClosed(False)
    w = BubbleWindow()
    w.show()
    app.exec()


if __name__ == "__main__":
    run_app()
