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
import re
import sys
from datetime import datetime, timedelta
from PyQt6.QtCore import (
    Qt, QThread, QTimer, pyqtSignal, QPoint, QRect, QSize,
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
    QFrame, QSizePolicy, QListWidget, QListWidgetItem,
    QTextEdit, QMessageBox, QDialog, QDialogButtonBox,
    QDateTimeEdit,
)

from src.core.chat_backend import ChatBackend
from src.services.reminder_service import ReminderCommandResult, ReminderService
from src.services.session_service import SessionService
from src.ui.cat_animation import CatAnimation


# ═══════════════════════════════════════════════════════════════════════════════
# 主题颜色定义 (主题名, 用户气泡颜色, AI气泡颜色)
# ═══════════════════════════════════════════════════════════════════════════════

THEMES = [
    ("星蓝独白",   "#3B82F6", "#E5E7EB"),   # 星际蓝 + 冷浅灰
    ("紫垣金穗",   "#7C3AED", "#FBBF24"),   # 藤萝紫 + 麦芽黄
    ("碧苔珊瑚",   "#14B8A6", "#F87171"),   # 松石青 + 珊瑚粉
    ("藏青樱粉",   "#1E40AF", "#FECDD3"),   # 深海藏青 + 樱花粉
    ("碧落月白",   "#2E86AB", "#F5F7FA"),   # 碧落青 + 月白
    ("黛青檀烟",   "#5A724F", "#EBE3D5"),   # 远山黛 + 檀米色
    ("天青霁色",   "#4A6FA5", "#EEF2F7"),   # 霁蓝 + 素清白
]

HISTORY_PANEL_STYLESHEET = """
QWidget {
    background: transparent;
    color: #FEFFFF;
    border: none;
}
QFrame#historyCard {
    background: rgba(30, 47, 66, 0.96);
    border: 1px solid rgba(71, 112, 155, 0.45);
    border-radius: 18px;
}
QFrame#titleBar {
    background: rgba(71, 112, 155, 0.78);
    border: 1px solid rgba(254, 255, 255, 0.16);
    border-radius: 14px;
}
QLabel#historyTitle {
    color: #FEFFFF;
    font-size: 18px;
    font-weight: 700;
}
QLabel#historySubtitle {
    color: rgba(254, 255, 255, 0.72);
    font-size: 12px;
}
QListWidget {
    background: rgba(254, 255, 255, 0.08);
    border: 1px solid rgba(71, 112, 155, 0.38);
    border-radius: 14px;
    padding: 6px;
    outline: none;
}
QListWidget::item {
    background: transparent;
    border-radius: 10px;
    padding: 12px 14px;
    margin: 3px 0;
    color: #FEFFFF;
}
QListWidget::item:selected {
    background: rgba(71, 112, 155, 0.55);
    color: #FEFFFF;
}
QListWidget::item:hover {
    background: rgba(71, 112, 155, 0.22);
}
QTextEdit {
    background: rgba(254, 255, 255, 0.08);
    border: 1px solid rgba(71, 112, 155, 0.38);
    border-radius: 14px;
    color: #FEFFFF;
    padding: 12px;
    selection-background-color: rgba(71, 112, 155, 0.45);
}
QPushButton {
    background: rgba(71, 112, 155, 0.34);
    color: #FEFFFF;
    border: 1px solid rgba(254, 255, 255, 0.18);
    border-radius: 12px;
    padding: 10px 16px;
    font-weight: 500;
}
QPushButton:hover {
    background: rgba(71, 112, 155, 0.5);
    border-color: rgba(254, 255, 255, 0.3);
}
QPushButton:pressed {
    background: rgba(71, 112, 155, 0.64);
}
QLineEdit, QDateTimeEdit {
    background: rgba(254, 255, 255, 0.08);
    border: 1px solid rgba(71, 112, 155, 0.4);
    border-radius: 14px;
    color: #FEFFFF;
    padding: 12px 14px;
    font-size: 16px;
    selection-background-color: rgba(71, 112, 155, 0.45);
}
QLineEdit::placeholder {
    color: rgba(254, 255, 255, 0.45);
}
QDateTimeEdit::drop-down {
    width: 30px;
    border: none;
    background: transparent;
}
QDateTimeEdit::down-arrow {
    width: 12px;
    height: 12px;
}
"""

REMINDER_PANEL_STYLESHEET = """
QWidget {
    background: transparent;
    color: #FEFFFF;
    border: none;
}
QFrame#historyCard {
    background: rgba(30, 47, 66, 0.96);
    border: 1px solid rgba(71, 112, 155, 0.45);
    border-radius: 18px;
}
QFrame#titleBar {
    background: rgba(71, 112, 155, 0.78);
    border: 1px solid rgba(254, 255, 255, 0.16);
    border-radius: 14px;
}
QLabel#historyTitle {
    color: #FEFFFF;
    font-size: 18px;
    font-weight: 700;
}
QLabel#historySubtitle {
    color: rgba(254, 255, 255, 0.72);
    font-size: 12px;
}
QListWidget {
    background: rgba(254, 255, 255, 0.08);
    border: 1px solid rgba(71, 112, 155, 0.38);
    border-radius: 14px;
    padding: 6px;
    outline: none;
}
QListWidget::item {
    background: transparent;
    border-radius: 10px;
    padding: 12px 14px;
    margin: 3px 0;
    color: #FEFFFF;
}
QListWidget::item:selected {
    background: rgba(71, 112, 155, 0.55);
    color: #FEFFFF;
}
QListWidget::item:hover {
    background: rgba(71, 112, 155, 0.22);
}
QTextEdit {
    background: rgba(254, 255, 255, 0.08);
    border: 1px solid rgba(71, 112, 155, 0.38);
    border-radius: 14px;
    color: #FEFFFF;
    padding: 12px;
    selection-background-color: rgba(71, 112, 155, 0.45);
}
QPushButton {
    background: rgba(71, 112, 155, 0.34);
    color: #FEFFFF;
    border: 1px solid rgba(254, 255, 255, 0.18);
    border-radius: 12px;
    padding: 10px 16px;
    font-weight: 500;
}
QPushButton:hover {
    background: rgba(71, 112, 155, 0.5);
    border-color: rgba(254, 255, 255, 0.3);
}
QPushButton:pressed {
    background: rgba(71, 112, 155, 0.64);
}
QLineEdit, QDateTimeEdit {
    background: rgba(254, 255, 255, 0.08);
    border: 1px solid rgba(71, 112, 155, 0.4);
    border-radius: 14px;
    color: #FEFFFF;
    padding: 12px 14px;
    font-size: 16px;
    selection-background-color: rgba(71, 112, 155, 0.45);
}
QLineEdit::placeholder {
    color: rgba(254, 255, 255, 0.45);
}
QDateTimeEdit::drop-down {
    width: 30px;
    border: none;
    background: transparent;
}
QDateTimeEdit::down-arrow {
    width: 12px;
    height: 12px;
}
"""


class DraggableFramelessMixin:
    """给无边框窗口提供基础拖动能力。"""

    def _init_drag_state(self) -> None:
        self._drag_active = False
        self._drag_offset = QPoint()
        self._drag_handles: list[QWidget] = []

    def _register_drag_handle(self, widget: QWidget) -> None:
        self._drag_handles.append(widget)
        widget.installEventFilter(self)

    def eventFilter(self, watched, event) -> bool:
        if watched in self._drag_handles:
            if event.type() == event.Type.MouseButtonPress and event.button() == Qt.MouseButton.LeftButton:
                self._drag_active = True
                self._drag_offset = event.globalPosition().toPoint() - self.frameGeometry().topLeft()
                return True
            if event.type() == event.Type.MouseMove and self._drag_active and (event.buttons() & Qt.MouseButton.LeftButton):
                self.move(event.globalPosition().toPoint() - self._drag_offset)
                return True
            if event.type() == event.Type.MouseButtonRelease:
                self._drag_active = False
                return True
        return super().eventFilter(watched, event)


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
            self.error.emit(self._format_error_message(exc))

    async def _consume(self) -> None:
        full = ""
        async for token in self._backend.send_message_stream(self._prompt, self._session_id):
            full += token
            self.chunk.emit(token)
        self.done.emit(full)

    @staticmethod
    def _format_error_message(exc: Exception) -> str:
        message = str(exc).strip()
        if message:
            return message
        exc_repr = repr(exc).strip()
        if exc_repr and exc_repr != f"{exc.__class__.__name__}()":
            return exc_repr
        return exc.__class__.__name__


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

    theme_changed = pyqtSignal(str, str)
    theme_selected = pyqtSignal(int)

    def __init__(self, parent: QWidget) -> None:
        super().__init__(parent)
        self._parent_window = parent
        self._selected_idx = 0
        self._theme_buttons: list[QPushButton] = []
        self._build_ui()

    def _build_ui(self) -> None:
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        self.setWindowFlags(
            Qt.WindowType.FramelessWindowHint
            | Qt.WindowType.Tool,
        )
        self.setFixedWidth(260)

        main_layout = QVBoxLayout(self)
        main_layout.setContentsMargins(12, 12, 12, 12)
        main_layout.setSpacing(12)

        # 标题
        title = QLabel("◈ 主题设置")
        title.setFont(QFont("Microsoft YaHei UI", 13, QFont.Weight.Bold))
        title.setStyleSheet("QLabel { color: #F1F5F9; background: transparent; }")
        main_layout.addWidget(title)

        # 分隔线
        separator = QFrame()
        separator.setFrameShape(QFrame.Shape.HLine)
        separator.setStyleSheet("QFrame { background: rgba(255,255,255,0.1); border: none; }")
        main_layout.addWidget(separator)

        # 副标题
        subtitle = QLabel("选择你喜欢的主题配色")
        subtitle.setFont(QFont("Microsoft YaHei UI", 10))
        subtitle.setStyleSheet("QLabel { color: #94A3B8; background: transparent; }")
        main_layout.addWidget(subtitle)

        # 主题卡片网格
        grid_layout = QGridLayout()
        grid_layout.setSpacing(10)
        
        cols = 2
        for i, theme_data in enumerate(THEMES):
            name = theme_data[0]
            user_color = theme_data[1]
            assistant_color = theme_data[2]
            
            # 创建主题卡片
            card = self._create_theme_card(name, user_color, assistant_color, i)
            self._theme_buttons.append(card)
            
            row, col = divmod(i, cols)
            grid_layout.addWidget(card, row, col)
        
        main_layout.addLayout(grid_layout)
        main_layout.addStretch(1)

        self._update_card_states()

        self.setStyleSheet("QWidget { background: rgba(20, 24, 40, 0.95); }")

    def _create_theme_card(self, name: str, user_color: str, assistant_color: str, idx: int) -> QPushButton:
        """创建主题卡片按钮"""
        card = QPushButton(self)
        card.setFixedHeight(60)
        card.setCursor(Qt.CursorShape.PointingHandCursor)
        card.setFont(QFont("Microsoft YaHei UI", 10, QFont.Weight.Medium))
        card.setProperty("themeIdx", idx)
        
        # 创建预览气泡
        preview = QPixmap(100, 30)
        preview.fill(QColor(user_color))
        painter = QPainter(preview)
        # 绘制用户气泡
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(QColor(user_color))
        painter.drawRoundedRect(0, 2, 40, 20, 6, 6)
        # 绘制AI气泡
        painter.setBrush(QColor(assistant_color))
        painter.drawRoundedRect(50, 8, 50, 20, 6, 6)
        painter.end()
        
        card.setIcon(QIcon(preview))
        card.setIconSize(QSize(100, 30))
        card.setText(f"  {name}")
        card.setLayoutDirection(Qt.LayoutDirection.LeftToRight)
        
        # 获取text位置，调整
        card.setStyleSheet("""
            QPushButton {
                background: rgba(30, 41, 59, 0.8);
                border: 2px solid rgba(255, 255, 255, 0.1);
                border-radius: 10px;
                padding: 6px 8px;
                text-align: left;
                color: #F1F5F9;
            }
            QPushButton:hover {
                background: rgba(50, 61, 79, 0.9);
                border: 2px solid rgba(99, 102, 241, 0.5);
            }
        """)
        
        card.clicked.connect(lambda _, index=idx: self._on_theme_selected(index))
        return card

    def _update_card_states(self) -> None:
        for i, card in enumerate(self._theme_buttons):
            is_selected = i == self._selected_idx
            if is_selected:
                card.setStyleSheet("""
                    QPushButton {
                        background: rgba(99, 102, 241, 0.25);
                        border: 2px solid #6366F1;
                        border-radius: 10px;
                        padding: 6px 8px;
                        text-align: left;
                        color: #E0E7FF;
                    }
                    QPushButton:hover {
                        background: rgba(99, 102, 241, 0.35);
                        border: 2px solid #818CF8;
                    }
                """)
            else:
                card.setStyleSheet("""
                    QPushButton {
                        background: rgba(30, 41, 59, 0.8);
                        border: 2px solid rgba(255, 255, 255, 0.1);
                        border-radius: 10px;
                        padding: 6px 8px;
                        text-align: left;
                        color: #F1F5F9;
                    }
                    QPushButton:hover {
                        background: rgba(50, 61, 79, 0.9);
                        border: 2px solid rgba(99, 102, 241, 0.5);
                    }
                """)

    def _on_theme_selected(self, idx: int) -> None:
        self._selected_idx = idx
        self._update_card_states()
        theme_data = THEMES[idx]
        self.theme_selected.emit(idx)
        self.theme_changed.emit(theme_data[1], theme_data[2])

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


class HistoryWindow(DraggableFramelessMixin, QWidget):

    preview_requested = pyqtSignal(int)
    session_selected = pyqtSignal(int)
    new_session_requested = pyqtSignal()
    delete_session_requested = pyqtSignal(int)

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._init_drag_state()
        self._build_ui()

    def _build_ui(self) -> None:
        self.setWindowTitle("Deskmate History")
        self.setWindowFlags(
            Qt.WindowType.FramelessWindowHint
            | Qt.WindowType.WindowStaysOnTopHint
            | Qt.WindowType.Tool
        )
        self.resize(920, 620)
        self.setStyleSheet(HISTORY_PANEL_STYLESHEET)

        outer = QVBoxLayout(self)
        outer.setContentsMargins(18, 18, 18, 18)
        outer.setSpacing(0)

        card = QFrame(self)
        card.setObjectName("historyCard")
        outer.addWidget(card)

        layout = QVBoxLayout(card)
        layout.setContentsMargins(20, 20, 20, 20)
        layout.setSpacing(14)

        title = QLabel("多轮对话")
        title.setObjectName("historyTitle")
        title_bar = QFrame(self)
        title_bar.setObjectName("titleBar")
        header = QHBoxLayout(title_bar)
        header.setContentsMargins(14, 10, 10, 10)
        header.setSpacing(8)
        header.addWidget(title)
        header.addStretch(1)

        close_btn = QPushButton("x")
        close_btn.setFixedSize(34, 34)
        close_btn.clicked.connect(self.close)
        header.addWidget(close_btn)
        layout.addWidget(title_bar)
        self._register_drag_handle(title_bar)

        subtitle = QLabel("查看历史会话，切换上下文，继续之前的聊天。")
        subtitle.setObjectName("historySubtitle")
        layout.addWidget(subtitle)

        body = QHBoxLayout()
        body.setSpacing(14)
        layout.addLayout(body, 1)

        left = QVBoxLayout()
        left.setSpacing(10)
        body.addLayout(left, 2)

        self._session_list = QListWidget(self)
        self._session_list.itemSelectionChanged.connect(self._on_selection_changed)
        self._session_list.itemDoubleClicked.connect(self._on_item_activated)
        left.addWidget(self._session_list, 1)

        left_buttons = QHBoxLayout()
        left_buttons.setSpacing(8)
        left.addLayout(left_buttons)

        new_btn = QPushButton("新建对话")
        new_btn.clicked.connect(self.new_session_requested.emit)
        left_buttons.addWidget(new_btn)

        open_btn = QPushButton("继续对话")
        open_btn.clicked.connect(self._emit_current_selection)
        left_buttons.addWidget(open_btn)

        delete_btn = QPushButton("删除")
        delete_btn.clicked.connect(self._delete_current_selection)
        left_buttons.addWidget(delete_btn)

        right = QVBoxLayout()
        right.setSpacing(10)
        body.addLayout(right, 3)

        preview_title = QLabel("会话内容预览")
        preview_title.setObjectName("historySubtitle")
        right.addWidget(preview_title)

        self._preview = QTextEdit(self)
        self._preview.setReadOnly(True)
        self._preview.setPlaceholderText("选择左侧会话后，这里会显示聊天记录。")
        right.addWidget(self._preview, 1)

    def populate_sessions(self, sessions: list[dict], current_session_id: int | None = None) -> None:
        self._session_list.blockSignals(True)
        self._session_list.clear()
        for session in sessions:
            label = session["title"]
            item = QListWidgetItem(label)
            item.setData(Qt.ItemDataRole.UserRole, session["id"])
            item.setToolTip(
                f'{session["title"]}\n创建: {session["created_at"]}\n更新: {session["updated_at"]}'
            )
            self._session_list.addItem(item)
            if current_session_id is not None and session["id"] == current_session_id:
                self._session_list.setCurrentItem(item)
        self._session_list.blockSignals(False)

    def set_preview(self, messages: list) -> None:
        if not messages:
            self._preview.setPlainText("这个会话还没有消息。")
            return

        blocks: list[str] = []
        for msg in messages:
            role = "你" if msg.role == "user" else "助手"
            blocks.append(f"{role}\n{msg.content}")
        self._preview.setPlainText("\n\n".join(blocks))
        cursor = self._preview.textCursor()
        cursor.movePosition(cursor.MoveOperation.End)
        self._preview.setTextCursor(cursor)

    def show_near_cursor(self) -> None:
        screen = QApplication.primaryScreen().availableGeometry()
        pos = QCursor.pos()
        x = min(max(screen.left() + 20, pos.x() - self.width() // 2), screen.right() - self.width() - 20)
        y = min(max(screen.top() + 20, pos.y() - self.height() // 3), screen.bottom() - self.height() - 20)
        self.move(x, y)
        self.show()
        self.raise_()
        self.activateWindow()

    def _on_selection_changed(self) -> None:
        item = self._session_list.currentItem()
        if item is None:
            self._preview.clear()
            return
        session_id = item.data(Qt.ItemDataRole.UserRole)
        self.preview_requested.emit(session_id)

    def _on_item_activated(self, item: QListWidgetItem) -> None:
        session_id = item.data(Qt.ItemDataRole.UserRole)
        self.session_selected.emit(session_id)

    def _emit_current_selection(self) -> None:
        item = self._session_list.currentItem()
        if item is None:
            return
        self.session_selected.emit(item.data(Qt.ItemDataRole.UserRole))

    def _delete_current_selection(self) -> None:
        item = self._session_list.currentItem()
        if item is None:
            return
        self.delete_session_requested.emit(item.data(Qt.ItemDataRole.UserRole))


class ReminderCreateDialog(DraggableFramelessMixin, QDialog):

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._init_drag_state()
        self.setWindowTitle("新建提醒")
        self.setModal(True)
        self.setWindowFlags(
            Qt.WindowType.FramelessWindowHint
            | Qt.WindowType.Dialog
            | Qt.WindowType.WindowStaysOnTopHint
        )
        self.resize(420, 260)
        self.setStyleSheet(REMINDER_PANEL_STYLESHEET)
        self._build_ui()

    def _build_ui(self) -> None:
        layout = QVBoxLayout(self)
        layout.setContentsMargins(20, 20, 20, 20)
        layout.setSpacing(12)

        title = QLabel("创建提醒")
        title.setObjectName("historyTitle")
        title_bar = QFrame(self)
        title_bar.setObjectName("titleBar")
        header = QHBoxLayout(title_bar)
        header.setContentsMargins(14, 10, 10, 10)
        header.setSpacing(8)
        header.addWidget(title)
        header.addStretch(1)

        close_btn = QPushButton("x")
        close_btn.setFixedSize(34, 34)
        close_btn.clicked.connect(self.reject)
        header.addWidget(close_btn)
        layout.addWidget(title_bar)
        self._register_drag_handle(title_bar)

        self._title_input = QLineEdit(self)
        self._title_input.setPlaceholderText("提醒标题，例如：提交验收材料")
        layout.addWidget(self._title_input)

        self._content_input = QTextEdit(self)
        self._content_input.setPlaceholderText("补充说明，可选")
        self._content_input.setFixedHeight(90)
        layout.addWidget(self._content_input)

        self._time_input = QDateTimeEdit(self)
        self._time_input.setCalendarPopup(True)
        self._time_input.setDateTime(datetime.now() + timedelta(minutes=10))
        self._time_input.setDisplayFormat("yyyy-MM-dd HH:mm")
        layout.addWidget(self._time_input)

        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel,
            parent=self,
        )
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

    def get_payload(self) -> tuple[str, str, datetime]:
        return (
            self._title_input.text().strip(),
            self._content_input.toPlainText().strip(),
            self._time_input.dateTime().toPyDateTime(),
        )


class ReminderWindow(DraggableFramelessMixin, QWidget):

    create_requested = pyqtSignal()
    snooze_requested = pyqtSignal(int)
    complete_requested = pyqtSignal(int)
    cancel_requested = pyqtSignal(int)

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._init_drag_state()
        self._build_ui()

    def _build_ui(self) -> None:
        self.setWindowTitle("Reminders")
        self.setWindowFlags(
            Qt.WindowType.FramelessWindowHint
            | Qt.WindowType.WindowStaysOnTopHint
            | Qt.WindowType.Tool
        )
        self.resize(920, 620)
        self.setStyleSheet(REMINDER_PANEL_STYLESHEET)

        outer = QVBoxLayout(self)
        outer.setContentsMargins(18, 18, 18, 18)
        outer.setSpacing(0)

        card = QFrame(self)
        card.setObjectName("historyCard")
        outer.addWidget(card)

        layout = QVBoxLayout(card)
        layout.setContentsMargins(20, 20, 20, 20)
        layout.setSpacing(14)

        title = QLabel("提醒与待办")
        title.setObjectName("historyTitle")
        title_bar = QFrame(self)
        title_bar.setObjectName("titleBar")
        header = QHBoxLayout(title_bar)
        header.setContentsMargins(14, 10, 10, 10)
        header.setSpacing(8)
        header.addWidget(title)
        header.addStretch(1)

        close_btn = QPushButton("x")
        close_btn.setFixedSize(34, 34)
        close_btn.clicked.connect(self.close)
        header.addWidget(close_btn)
        layout.addWidget(title_bar)
        self._register_drag_handle(title_bar)

        subtitle = QLabel("创建、查看和处理即将到来的提醒。")
        subtitle.setObjectName("historySubtitle")
        layout.addWidget(subtitle)

        body = QHBoxLayout()
        body.setSpacing(14)
        layout.addLayout(body, 1)

        left = QVBoxLayout()
        left.setSpacing(10)
        body.addLayout(left, 2)

        self._list = QListWidget(self)
        self._list.itemSelectionChanged.connect(self._refresh_detail)
        left.addWidget(self._list, 1)

        left_buttons = QHBoxLayout()
        left_buttons.setSpacing(8)
        left.addLayout(left_buttons)

        new_btn = QPushButton("新建提醒")
        new_btn.clicked.connect(self.create_requested.emit)
        left_buttons.addWidget(new_btn)

        snooze_btn = QPushButton("稍后10分钟")
        snooze_btn.clicked.connect(self._snooze_current)
        left_buttons.addWidget(snooze_btn)

        right = QVBoxLayout()
        right.setSpacing(10)
        body.addLayout(right, 3)

        self._detail = QTextEdit(self)
        self._detail.setReadOnly(True)
        self._detail.setPlaceholderText("选择左侧提醒后，这里会显示详情。")
        right.addWidget(self._detail, 1)

        right_buttons = QHBoxLayout()
        right_buttons.setSpacing(8)
        right.addLayout(right_buttons)

        complete_btn = QPushButton("完成")
        complete_btn.clicked.connect(self._complete_current)
        right_buttons.addWidget(complete_btn)

        cancel_btn = QPushButton("删除")
        cancel_btn.clicked.connect(self._cancel_current)
        right_buttons.addWidget(cancel_btn)

    def populate(self, reminders: list) -> None:
        self._list.clear()
        for reminder in reminders:
            item = QListWidgetItem(f"[{reminder.status}] {reminder.title}")
            item.setData(Qt.ItemDataRole.UserRole, reminder)
            self._list.addItem(item)
        if self._list.count() > 0 and self._list.currentRow() < 0:
            self._list.setCurrentRow(0)
        else:
            self._refresh_detail()

    def show_near_cursor(self) -> None:
        screen = QApplication.primaryScreen().availableGeometry()
        pos = QCursor.pos()
        x = min(max(screen.left() + 20, pos.x() - self.width() // 2), screen.right() - self.width() - 20)
        y = min(max(screen.top() + 20, pos.y() - self.height() // 3), screen.bottom() - self.height() - 20)
        self.move(x, y)
        self.show()
        self.raise_()
        self.activateWindow()

    def _current_reminder(self):
        item = self._list.currentItem()
        if item is None:
            return None
        return item.data(Qt.ItemDataRole.UserRole)

    def _refresh_detail(self) -> None:
        reminder = self._current_reminder()
        if reminder is None:
            self._detail.clear()
            return

        lines = [
            f"标题：{reminder.title}",
            f"状态：{reminder.status}",
            f"提醒时间：{reminder.remind_at}",
        ]
        if reminder.content:
            lines.append("")
            lines.append(reminder.content)
        self._detail.setPlainText("\n".join(lines))

    def _snooze_current(self) -> None:
        reminder = self._current_reminder()
        if reminder is not None:
            self.snooze_requested.emit(reminder.id)

    def _complete_current(self) -> None:
        reminder = self._current_reminder()
        if reminder is not None:
            self.complete_requested.emit(reminder.id)

    def _cancel_current(self) -> None:
        reminder = self._current_reminder()
        if reminder is not None:
            self.cancel_requested.emit(reminder.id)


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
        self._refresh_bubble_layout()

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
        self._refresh_bubble_layout()

    def _refresh_bubble_layout(self) -> None:
        self._label.setMaximumWidth(self.MAX_W - 20)
        self._label.adjustSize()
        if self.layout() is not None:
            self.layout().invalidate()
            self.layout().activate()
        self.adjustSize()
        self.updateGeometry()
        if self.height() < self.MIN_H:
            self.setMinimumHeight(self.MIN_H)
        if self.parentWidget() is not None:
            self.parentWidget().updateGeometry()
            if self.parentWidget().layout() is not None:
                self.parentWidget().layout().invalidate()
                self.parentWidget().layout().activate()

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
        self._theme_user = THEMES[0][1]
        self._theme_assistant = THEMES[0][2]
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

    def add_message(self, role: str, text: str) -> None:
        bubble = ChatBubble(
            text,
            role,
            opacity_factor=1.0,
            theme_user=self._theme_user,
            theme_assistant=self._theme_assistant,
        )
        self._add_row(bubble)
        self._refresh_opacities()
        self._recompute_and_scroll()

    def load_history(self, messages: list, limit: int = 20) -> None:
        self.clear_messages()
        for msg in messages[-limit:]:
            self.add_message(msg.role, msg.content)

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

    def finalize_pending(self, drop_if_empty: bool = False) -> None:
        if self._pending_chunks and self._pending_bubble:
            joined = "".join(self._pending_chunks)
            self._pending_chunks.clear()
            self._pending_bubble.append_text(joined)
        elif drop_if_empty and self._pending_bubble is not None and not self._pending_bubble._text.strip():
            self._remove_bubble(self._pending_bubble)
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

    def _remove_bubble(self, bubble: ChatBubble) -> None:
        if bubble not in self._messages:
            return
        row_idx = self._messages.index(bubble)
        self._remove_row(row_idx)
        self._messages.pop(row_idx)
        bubble.deleteLater()


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

    def set_busy(self, busy: bool) -> None:
        self._msg_list._input.setEnabled(not busy)
        self._msg_list._input.setPlaceholderText("正在请求回复..." if busy else "Message...")
        if not busy:
            self._msg_list._input.setFocus()

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
    reminder_triggered = pyqtSignal(object)
    MARGIN = 24
    _ICON_SIZE = 64

    def __init__(self) -> None:
        super().__init__()

        self._backend = ChatBackend()
        self._stream_worker: StreamingWorker | None = None
        self._current_theme_idx = 0
        self._tray_flash_timer: QTimer | None = None
        self._tray_flash_steps = 0
        self._tray_icon_visible = True
        self._tray_icon_default = QIcon(CatAnimation(self._ICON_SIZE).get_current_frame())
        blank = QPixmap(self._ICON_SIZE, self._ICON_SIZE)
        blank.fill(Qt.GlobalColor.transparent)
        self._tray_icon_blank = QIcon(blank)
        self._reminder_service = ReminderService(
            db=self._backend.db,
            on_trigger=self._handle_scheduler_trigger,
        )
        self._session_service = SessionService(self._backend)

        self._state = "rest"
        self.reminder_triggered.connect(self._display_reminder)

        self._setup_window()
        self._build_star_button()
        self._build_input()
        self._build_settings_panel()
        self._build_history_window()
        self._build_reminder_window()
        self._setup_tray()
        self._configure_tray_menu()
        self._reminder_service.start()

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

    def _build_history_window(self) -> None:
        self._history_window = HistoryWindow(self)
        self._history_window.hide()
        self._history_window.preview_requested.connect(self._preview_session)
        self._history_window.session_selected.connect(self._show_session)
        self._history_window.new_session_requested.connect(self._create_new_session)
        self._history_window.delete_session_requested.connect(self._delete_session)

    def _build_reminder_window(self) -> None:
        self._reminder_window = ReminderWindow(self)
        self._reminder_window.hide()
        self._reminder_window.create_requested.connect(self._show_create_reminder_dialog)
        self._reminder_window.snooze_requested.connect(self._snooze_reminder)
        self._reminder_window.complete_requested.connect(self._complete_reminder)
        self._reminder_window.cancel_requested.connect(self._cancel_reminder)

    def _setup_tray(self) -> None:
        self._tray = QSystemTrayIcon(self)
        self._tray.setIcon(self._tray_icon_default)
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
        menu.setStyleSheet("""
            QMenu {
                background: #1E293B;
                border: 1px solid rgba(99, 102, 241, 0.3);
                border-radius: 12px;
                padding: 8px;
                min-width: 200px;
            }
            QMenu::item {
                color: #F1F5F9;
                padding: 10px 16px;
                border-radius: 8px;
                font-family: "Microsoft YaHei UI";
                font-size: 13px;
            }
            QMenu::item:selected {
                background: rgba(99, 102, 241, 0.3);
            }
            QMenu::item:checked {
                background: rgba(99, 102, 241, 0.4);
                color: #A5B4FC;
            }
            QMenu::separator {
                background: rgba(255,255,255,0.1);
                height: 1px;
                margin: 6px 12px;
            }
        """)
        
        # 显示标题
        title_action = menu.addAction("◈ 切换主题")
        title_action.setEnabled(False)
        title_action.setFont(QFont("Microsoft YaHei UI", 11, QFont.Weight.Bold))
        menu.addSeparator()
        
        # 添加每个主题
        for i, theme_data in enumerate(THEMES):
            name = theme_data[0]
            user_color = theme_data[1]
            assistant_color = theme_data[2]
            
            # 创建双色预览图标 (28x14: 左半用户色，右半AI色)
            preview = QPixmap(28, 14)
            preview.fill(QColor(user_color))
            painter = QPainter(preview)
            painter.fillRect(14, 0, 14, 14, QColor(assistant_color))
            painter.end()
            
            action = menu.addAction(f"  {name}")
            action.setIcon(QIcon(preview))
            action.setData(i)
            
            # 如果是当前主题，添加选中标记
            if i == getattr(self, '_current_theme_idx', 0):
                action.setCheckable(True)
                action.setChecked(True)
        
        menu.addSeparator()
        cancel_action = menu.addAction("取消")
        
        chosen = menu.exec(QCursor.pos())
        if chosen and chosen.data() is not None and chosen != cancel_action:
            idx = chosen.data()
            theme_data = THEMES[idx]
            self._current_theme_idx = idx
            self._input._msg_list.set_theme(theme_data[1], theme_data[2])

    def _on_theme_changed(self, user: str, assistant: str) -> None:
        self._input._msg_list.set_theme(user, assistant)

    def _show_settings_panel(self) -> None:
        self._settings_panel.show_at_star(self._star_geometry())

    def _show_history_window(self) -> None:
        self._refresh_history_window()
        self._history_window.show_near_cursor()

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

    def _on_star_clicked(self) -> None:
        if self._state == "active":
            self._star.set_animation_state('idle')
        else:
            self._star.set_animation_state('sleeping')

    def _activate_input(self) -> None:
        self._state = "active"
        if self._session_service.current_session_id is None:
            self._create_new_session()
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
        if self._stream_worker and self._stream_worker.isRunning():
            return
        session_id = self._session_service.ensure_session()

        self._input._msg_list.add_user_bubble(content)
        command_result = self._handle_local_reminder_command(content)
        if command_result.handled:
            self._session_service.add_message("user", content)
            self._input._msg_list.add_message("assistant", command_result.reply)
            self._session_service.add_message("assistant", command_result.reply)
            self._refresh_history_window()
            self._refresh_reminder_window()
            return
        self._input.set_busy(True)
        self._input._msg_list.add_assistant_bubble()
        self._call_stream(content, session_id)

    def _call_stream(self, content: str, session_id: int) -> None:
        if self._stream_worker and self._stream_worker.isRunning():
            return
        self._stream_worker = StreamingWorker(
            backend=self._backend,
            prompt=content,
            session_id=session_id,
        )
        self._stream_worker.chunk.connect(self._on_stream_chunk)
        self._stream_worker.done.connect(self._on_stream_done)
        self._stream_worker.error.connect(self._on_error)
        self._stream_worker.start()

    def _on_stream_chunk(self, chunk: str) -> None:
        self._input._msg_list.append_to_pending(chunk)

    def _on_stream_done(self, full_text: str) -> None:
        self._input._msg_list.finalize_pending()
        self._input.set_busy(False)
        self._refresh_history_window()
        self._stream_worker = None

    def _on_error(self, err: str) -> None:
        self._input._msg_list.finalize_pending(drop_if_empty=True)
        detail = err.strip() if err and err.strip() else "未知错误"
        error_text = f"抱歉，当前模型请求失败：{detail}"
        self._input._msg_list.add_message("assistant", error_text)
        self._session_service.add_message("assistant", error_text)
        self._input.set_busy(False)
        self._refresh_history_window()
        self._stream_worker = None

    def _refresh_history_window(self) -> None:
        current_session_id = self._session_service.current_session_id
        sessions = self._session_service.get_recent_sessions()
        self._history_window.populate_sessions(sessions, current_session_id)
        if current_session_id is not None:
            self._history_window.set_preview(self._session_service.get_current_history())
        else:
            self._history_window.set_preview([])

    def _create_new_session(self) -> None:
        self._session_service.create_new_session()
        self._input._msg_list.clear_messages()
        self._refresh_history_window()

    def _preview_session(self, session_id: int) -> None:
        self._history_window.set_preview(self._session_service.preview_session(session_id))

    def _show_session(self, session_id: int) -> None:
        history = self._session_service.switch_session(session_id)
        self._history_window.set_preview(history)
        self._input._msg_list.load_history(history)
        self._state = "active"
        self._input.show_input()
        self._star.set_animation_state('idle')
        self._history_window.hide()

    def _delete_session(self, session_id: int) -> None:
        reply = QMessageBox.question(
            self,
            "删除会话",
            "确定删除这个历史会话吗？",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No,
        )
        if reply != QMessageBox.StandardButton.Yes:
            return

        result = self._session_service.delete_session(session_id)
        if result.current_session_id is None:
            self._input._msg_list.clear_messages()
        else:
            self._input._msg_list.load_history(result.current_history)
        self._refresh_history_window()

    def _handle_scheduler_trigger(self, reminder) -> None:
        self.reminder_triggered.emit(reminder)

    def _display_reminder(self, reminder) -> None:
        self._state = "active"
        if self._session_service.current_session_id is None:
            self._create_new_session()
        self._input.show_input()
        self._star.set_animation_state("angry")
        text = self._reminder_service.format_trigger_message(reminder)
        self._input._msg_list.add_message("assistant", text)
        self._session_service.add_message("assistant", text)
        self._start_tray_flash()
        self._tray.showMessage(
            "Deskmate 提醒",
            self._reminder_service.format_trigger_notification(reminder),
            QSystemTrayIcon.MessageIcon.Information,
            5000,
        )
        self._refresh_history_window()

    def _start_tray_flash(self) -> None:
        self._tray_flash_steps = 8
        self._tray_icon_visible = False
        if self._tray_flash_timer is None:
            self._tray_flash_timer = QTimer(self)
            self._tray_flash_timer.timeout.connect(self._toggle_tray_flash)
        if not self._tray_flash_timer.isActive():
            self._tray_flash_timer.start(420)

    def _toggle_tray_flash(self) -> None:
        self._tray.setIcon(self._tray_icon_default if self._tray_icon_visible else self._tray_icon_blank)
        self._tray_icon_visible = not self._tray_icon_visible
        self._tray_flash_steps -= 1
        if self._tray_flash_steps <= 0 and self._tray_flash_timer is not None:
            self._tray_flash_timer.stop()
            self._tray.setIcon(self._tray_icon_default)
            self._tray_icon_visible = True

    def _handle_local_reminder_command(self, content: str) -> ReminderCommandResult:
        return self._reminder_service.handle_chat_command(content)

    def _configure_tray_menu(self) -> None:
        menu = QMenu(self)
        menu.addAction("打开聊天", self._show_window)
        menu.addAction("多轮对话", self._show_history_window)
        menu.addAction("提醒与待办", self._show_reminder_window)
        menu.addSeparator()
        menu.addAction("新建提醒", self._show_create_reminder_dialog)
        menu.addSeparator()
        menu.addAction("切换主题", self._show_theme_menu)
        menu.addSeparator()
        menu.addAction("退出", self.close)
        self._tray.setContextMenu(menu)

    def _show_star_context_menu(self) -> None:
        menu = QMenu(self)
        menu.setStyleSheet("""
            QMenu {
                background: #1E293B;
                border: 1px solid rgba(99, 102, 241, 0.3);
                border-radius: 12px;
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
            QMenu::indicator {
                width: 14px;
                height: 14px;
            }
        """)

        menu.addAction("打开聊天")
        menu.addAction("多轮对话")
        menu.addAction("提醒与待办")
        menu.addSeparator()
        menu.addAction("新建提醒")
        menu.addSeparator()
        
        # 主题子菜单
        theme_submenu = QMenu("◈ 切换主题", menu)
        theme_submenu.setStyleSheet("""
            QMenu {
                background: #1E293B;
                border: 1px solid rgba(99, 102, 241, 0.3);
                border-radius: 12px;
                padding: 8px;
            }
            QMenu::item {
                color: #F1F5F9;
                padding: 10px 16px;
                border-radius: 8px;
                font-family: "Microsoft YaHei UI";
                font-size: 13px;
            }
            QMenu::item:selected {
                background: rgba(99, 102, 241, 0.3);
            }
        """)
        
        for i, theme_data in enumerate(THEMES):
            name = theme_data[0]
            user_color = theme_data[1]
            assistant_color = theme_data[2]
            
            # 创建双色预览图标
            preview = QPixmap(28, 14)
            preview.fill(QColor(user_color))
            painter = QPainter(preview)
            painter.fillRect(14, 0, 14, 14, QColor(assistant_color))
            painter.end()
            
            action = theme_submenu.addAction(f"  {name}")
            action.setIcon(QIcon(preview))
            action.setData(i)
            
            # 当前主题标记
            if i == getattr(self, '_current_theme_idx', 0):
                action.setCheckable(True)
                action.setChecked(True)
        
        menu.addMenu(theme_submenu)
        menu.addSeparator()
        menu.addAction("退出")

        action = menu.exec(QCursor.pos())
        if action:
            text = action.text().strip()
            if text == "打开聊天":
                self._show_window()
            elif text == "多轮对话":
                self._show_history_window()
            elif text == "提醒与待办":
                self._show_reminder_window()
            elif text == "新建提醒":
                self._show_create_reminder_dialog()
            elif text == "退出":
                self.close()
                QApplication.instance().quit()
            else:
                # 检查是否是主题选择
                for i, theme_data in enumerate(THEMES):
                    if text == theme_data[0]:
                        self._current_theme_idx = i
                        self._input._msg_list.set_theme(theme_data[1], theme_data[2])
                        break

    def _show_reminder_window(self) -> None:
        self._refresh_reminder_window()
        self._reminder_window.show_near_cursor()

    def _refresh_reminder_window(self) -> None:
        self._reminder_window.populate(self._reminder_service.list_reminders())

    def _show_create_reminder_dialog(self) -> None:
        dialog = ReminderCreateDialog(self)
        if dialog.exec() != QDialog.DialogCode.Accepted:
            return

        title, content, remind_at = dialog.get_payload()
        validation_error = self._reminder_service.validate_manual_reminder(title, remind_at)
        if validation_error:
            QMessageBox.warning(self, "提醒", validation_error)
            return

        reminder = self._reminder_service.create_reminder(
            title=title,
            content=content,
            remind_at=remind_at,
        )
        self._input._msg_list.add_message(
            "assistant",
            self._reminder_service.format_created_reply(reminder),
        )
        self._refresh_reminder_window()

    def _snooze_reminder(self, reminder_id: int) -> None:
        reminder = self._reminder_service.snooze_reminder(reminder_id, minutes=10)
        if reminder is not None:
            self._input._msg_list.add_message(
                "assistant",
                self._reminder_service.format_snoozed_reply(reminder, minutes=10),
            )
            self._refresh_reminder_window()

    def _complete_reminder(self, reminder_id: int) -> None:
        self._reminder_service.complete_reminder(reminder_id)
        self._refresh_reminder_window()

    def _cancel_reminder(self, reminder_id: int) -> None:
        self._reminder_service.cancel_reminder(reminder_id)
        self._refresh_reminder_window()

    def closeEvent(self, e) -> None:
        self._tray.hide()
        self._history_window.hide()
        self._settings_panel.hide()
        self._reminder_window.hide()
        self._reminder_service.shutdown()
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
