"""
Deskmate 气泡助手 —— 微信式对话架构

架构说明：
  - 全屏透明画布：showMaximized() + WA_TranslucentBackground
  - 穿透：默认 WindowTransparentForInput，仅星星区域恢复交互
  - InputPanel：内嵌聊天消息列表，用户消息靠右，AI回复靠左
  - 流式：StreamingWorker 驱动打字机效果，文字追加到固定气泡中
"""
from __future__ import annotations

import asyncio
from PyQt6.QtCore import (
    Qt, QThread, QTimer, pyqtSignal, QPoint, QRect,
)
from PyQt6.QtGui import (
    QIcon, QPixmap, QPainter, QColor, QFont, QFontMetrics,
    QMouseEvent, QPainterPath,
)
from PyQt6.QtWidgets import (
    QApplication, QWidget, QLabel, QLineEdit,
    QGraphicsDropShadowEffect,
    QMenu, QSystemTrayIcon,
    QScrollArea, QVBoxLayout, QHBoxLayout,
    QFrame, QSizePolicy,
)

from src.core.chat_backend import ChatBackend
from src.ui.bubble_icons import get_icon


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
            full = ""
            loop = asyncio.new_event_loop()
            asyncio.set_event_loop(loop)
            async def consume():
                nonlocal full
                async_gen = self._backend.send_message_stream(
                    self._prompt, self._session_id
                )
                async for token in async_gen:
                    full += token
                    self.chunk.emit(token)
                    await asyncio.sleep(0.02)  # 每个 token 后等 20ms，实现自然打字节奏
            loop.run_until_complete(consume())
            loop.close()
            self.done.emit(full)
        except Exception as exc:
            self.error.emit(str(exc))


# ═══════════════════════════════════════════════════════════════════════════════
# 四角星按钮
# ═══════════════════════════════════════════════════════════════════════════════

class StarButton(QWidget):
    clicked = pyqtSignal()
    double_clicked = pyqtSignal()
    drag_delta = pyqtSignal(QPoint)

    ICON_SIZE = 48

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.setFixedSize(self.ICON_SIZE, self.ICON_SIZE)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self._pixmap: QPixmap | None = None
        self._dragging = False
        self._drag_start = QPoint()
        self._moved_during_press = False
        self._click_timer = QTimer(self)
        self._click_timer.setSingleShot(True)
        self._click_timer.setInterval(200)
        self._click_timer.timeout.connect(self.clicked)

    def _ensure_pixmap(self) -> None:
        if self._pixmap is None:
            self._pixmap = get_icon(self.ICON_SIZE)

    def paintEvent(self, e) -> None:
        self._ensure_pixmap()
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform)
        painter.drawPixmap(self.rect(), self._pixmap)

    def mousePressEvent(self, e: QMouseEvent) -> None:
        if e.button() == Qt.MouseButton.LeftButton:
            self._dragging = True
            self._drag_start = e.globalPosition().toPoint()
            self._moved_during_press = False

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

    def mouseReleaseEvent(self, e: QMouseEvent) -> None:
        if e.button() == Qt.MouseButton.LeftButton:
            if not self._moved_during_press:
                self._click_timer.start()
        self._dragging = False

    def mouseDoubleClickEvent(self, e: QMouseEvent) -> None:
        if e.button() == Qt.MouseButton.LeftButton:
            self._click_timer.stop()
            self.double_clicked.emit()


# ═══════════════════════════════════════════════════════════════════════════════
# 聊天气泡
# ═══════════════════════════════════════════════════════════════════════════════

class ChatBubble(QFrame):
    """单个聊天气泡，role='user' 靠右，role='assistant' 靠左"""

    MAX_W = 220
    MIN_H = 28

    def __init__(self, text: str, role: str, parent=None) -> None:
        super().__init__(parent)
        self._role = role
        self._text = text
        self.setFrameShape(QFrame.Shape.NoFrame)
        self.setMinimumHeight(self.MIN_H)
        self.setMaximumWidth(self.MAX_W)
        self.setSizePolicy(QSizePolicy.Policy.Maximum, QSizePolicy.Policy.Minimum)

        self._label = QLabel(text, self)
        self._label.setFont(QFont("Microsoft YaHei UI", 12))
        self._label.setWordWrap(True)
        self._label.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        self._label.setMaximumWidth(self.MAX_W - 20)

        layout = QHBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)
        if role == "user":
            layout.addStretch(1)
            layout.addWidget(self._label)
        else:
            layout.addWidget(self._label)
            layout.addStretch(1)

        self.setStyleSheet(self._css())

    def _css(self) -> str:
        if self._role == "user":
            return (
                "QFrame {"
                "  background: rgba(60, 60, 60, 0.70);"
                "  border-radius: 10px;"
                "  padding: 6px 10px;"
                "}"
                "QLabel { color: #FFFFFF; background: transparent; }"
            )
        else:
            return (
                "QFrame {"
                "  background: rgba(15, 23, 42, 0.85);"
                "  border-radius: 10px;"
                "  padding: 6px 10px;"
                "}"
                "QLabel { color: #F1F5F9; background: transparent; }"
            )

    def append_text(self, chunk: str) -> None:
        self._text += chunk
        self._label.setText(self._text)
        self._label.setMaximumWidth(self.MAX_W - 20)
        if self.height() < self.MIN_H:
            self.setMinimumHeight(self.MIN_H)

    @staticmethod
    def estimate_height(text: str, max_w: int) -> int:
        """用字体度量预估算气泡高度，避免依赖 adjustSize()"""
        metrics = QFontMetrics(QFont("Microsoft YaHei UI", 12))
        rect = metrics.boundingRect(0, 0, max_w - 20, 0, int(Qt.TextFlag.TextWordWrap), text)
        raw_h = rect.height() + 12
        return max(raw_h, 28)


# ═══════════════════════════════════════════════════════════════════════════════
# 聊天消息列表
# ═══════════════════════════════════════════════════════════════════════════════

class ChatMessageList(QWidget):
    """
    垂直滚动消息列表，底部固定输入框。
    新消息出现在底部（输入框正上方），旧消息向上滚动，顶部叠加渐变实现向上消失。
    """

    PANEL_W = 300
    MAX_H = 400
    INPUT_H = 34
    MARGIN = 16
    BUBBLE_GAP = 6

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self._messages: list[ChatBubble] = []
        self._pending_bubble: ChatBubble | None = None
        self._batch_timer: QTimer | None = None
        self._pending_chunks: list[str] = []
        self._build_ui()

    def _build_ui(self) -> None:
        self.setFixedWidth(self.PANEL_W)
        self.setMaximumHeight(self.MAX_H)
        self.setMinimumHeight(150)
        self.setSizePolicy(QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Preferred)
        self.setStyleSheet("QWidget { background: transparent; }")

        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(0)

        # --- 渐变遮罩层（覆盖在 scroll area 顶部，实现向上消失） ---
        self._fade_widget = QWidget(self)
        self._fade_widget.setFixedHeight(36)
        self._fade_widget.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)
        self._fade_widget.setStyleSheet(
            "background: qlineargradient(x1:0,y1:0,x2:0,y2:1,"
            "stop:0:rgba(20,24,40,0.95),stop:1:rgba(20,24,40,0));"
        )
        self._fade_widget.lower()

        # --- 滚动区 ---
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
                background: rgba(255,255,255,0.08);
                width: 4px;
                margin: 0;
                border-radius: 2px;
            }
            QScrollBar::handle:vertical {
                background: rgba(255,255,255,0.2);
                border-radius: 2px;
                min-height: 30px;
            }
            QScrollBar::add-page, QScrollBar::sub-page { background: none; }
        """)

        # 消息容器：stretch 在顶部，新消息从底部往上堆
        self._container = QWidget()
        self._container.setStyleSheet("background: transparent;")
        self._container_layout = QVBoxLayout(self._container)
        self._container_layout.setSpacing(self.BUBBLE_GAP)
        self._container_layout.setContentsMargins(0, 0, 0, 0)
        self._container_layout.addStretch(1)  # stretch 在顶部，推消息往下（贴着输入框）

        self._scroll.setWidget(self._container)
        outer.addWidget(self._scroll, 1)

        # --- 固定在底部的输入框 ---
        self._input = QLineEdit(self)
        self._input.setFixedHeight(34)
        self._input.setFont(QFont("Microsoft YaHei UI", 12))
        self._input.setPlaceholderText("Message...")
        self._input.setMaxLength(2000)
        self._input.setStyleSheet("""
            QLineEdit {
                background: rgba(255, 255, 255, 0.12);
                border: 1px solid rgba(255, 255, 255, 0.1);
                border-radius: 17px;
                color: #F1F5F9;
                padding: 0 16px;
                selection-background-color: rgba(59, 130, 246, 0.5);
            }
            QLineEdit::placeholder { color: rgba(148, 163, 184, 0.55); }
        """)
        self._input.setAttribute(Qt.WidgetAttribute.WA_MacShowFocusRect, False)
        outer.addWidget(self._input)

    def _update_fade_geometry(self) -> None:
        """把渐变遮罩定位到 scroll area 顶部，随 resize 更新"""
        self._fade_widget.setFixedWidth(self.PANEL_W)
        self._fade_widget.move(0, 0)
        self._fade_widget.raise_()

    def resizeEvent(self, event) -> None:
        super().resizeEvent(event)
        self._update_fade_geometry()

    def _add_row(self, bubble: ChatBubble) -> None:
        """在输入框正上方（stretch 之前）插入一行气泡"""
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

    def _recompute_and_scroll(self) -> None:
        """重新计算容器高度，滚动到底部（输入框正上方）"""
        self._container_layout.activate()
        total_h = self._container.sizeHint().height()
        self._container.setMinimumHeight(total_h)
        self._container.setMaximumHeight(total_h)
        self._update_fade_geometry()
        # 延迟滚动，确保布局完成后再滚
        QTimer.singleShot(5, self._scroll_to_bottom)

    def _scroll_to_bottom(self) -> None:
        bar = self._scroll.verticalScrollBar()
        bar.setValue(bar.maximum())

    def add_user_bubble(self, text: str) -> None:
        bubble = ChatBubble(text, "user")
        self._add_row(bubble)
        self._recompute_and_scroll()

    def add_assistant_bubble(self, text: str = "") -> ChatBubble:
        bubble = ChatBubble(text, "assistant")
        self._add_row(bubble)
        self._pending_bubble = bubble
        self._recompute_and_scroll()
        return bubble

    def append_to_pending(self, chunk: str) -> None:
        """批量收集 chunk，定时批量更新，减少布局重算"""
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
        for m in self._messages:
            m.deleteLater()
        self._messages.clear()
        self._pending_bubble = None
        self._pending_chunks.clear()
        # 只保留 stretch（最后一个 item）
        while self._container_layout.count() > 1:
            item = self._container_layout.takeAt(0)
            if item.layout():
                item.layout().deleteLater()
            elif item.widget():
                item.widget().deleteLater()
        self._recompute_and_scroll()


# ═══════════════════════════════════════════════════════════════════════════════
# 输入面板（含消息列表 + 固定底部输入框）
# ═══════════════════════════════════════════════════════════════════════════════

class ResizeGrip(QWidget):
    """右下角可拖动缩放的小三角"""

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
        # 画小三角，3条线
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
    """聊天面板：消息列表 + 固定底部输入框，锚定星星上方，右下角可拖动缩放"""

    send_clicked = pyqtSignal(str)
    RESIZE_HANDLE = 6
    MIN_PANEL_W = 200
    MAX_PANEL_W = 600
    MIN_PANEL_H = 150
    MAX_PANEL_H = 600
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
        self.setStyleSheet("""
            QWidget {
                background: rgba(20, 24, 40, 0.90);
                border: 1px solid rgba(255, 255, 255, 0.08);
                border-radius: 12px;
            }
        """)

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
        self._msg_list._fade_widget.setFixedWidth(new_w)
        self._msg_list._update_fade_geometry()
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
    _ICON_SIZE = 48

    def __init__(self) -> None:
        super().__init__()

        self._backend = ChatBackend()
        self._session_id = self._backend.create_session("气泡助手")
        self._stream_worker: StreamingWorker | None = None

        self._state = "rest"

        self._setup_window()
        self._build_star_button()
        self._build_input()
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

    def mousePressEvent(self, e: QMouseEvent) -> None:
        if not (e.button() == Qt.MouseButton.LeftButton):
            return
        gp = e.globalPosition().toPoint()
        if self._star_geometry().contains(gp):
            self._on_star_clicked()
            return

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
        self._star.double_clicked.connect(self._on_close)
        self._star.drag_delta.connect(self._move_star)

    def _on_close(self) -> None:
        self.close()
        QApplication.instance().quit()

    def _build_input(self) -> None:
        self._input = InputPanel(self)
        self._input.hide()
        self._input.send_clicked.connect(self._on_send)

    def _setup_tray(self) -> None:
        self._tray = QSystemTrayIcon(self)
        self._tray.setIcon(QIcon(get_icon(self._ICON_SIZE)))
        self._tray.setToolTip("气泡助手")
        menu = QMenu(self)
        menu.addAction("打开", self._show_window)
        menu.addSeparator()
        menu.addAction("退出", self.close)
        self._tray.setContextMenu(menu)
        self._tray.activated.connect(
            lambda r: self._show_window() if r else None
        )
        self._tray.show()

    def _show_window(self) -> None:
        if self._state == "rest":
            self._activate_input()
        else:
            self._on_input_cancel()
        self.activateWindow()
        self.raise_()

    def _on_star_clicked(self) -> None:
        if self._state == "rest":
            self._activate_input()
        else:
            self._on_input_cancel()

    def _activate_input(self) -> None:
        self._state = "active"
        self._input.show_input()

    def _on_input_cancel(self) -> None:
        if self._state != "active":
            return
        self._input.hide_input()
        self._state = "rest"

    def _on_send(self, content: str) -> None:
        if not content:
            return
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
