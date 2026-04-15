import asyncio
import random
import re
import html as html_module
from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, List, Literal, Optional

from PyQt6.QtCore import Qt, QThread, QTimer, pyqtSignal
from PyQt6.QtGui import QAction, QPixmap, QIcon, QColor, QPainter
from PyQt6.QtWidgets import (
    QAbstractItemView,
    QApplication,
    QDialog,
    QFileDialog,
    QHBoxLayout,
    QInputDialog,
    QLabel,
    QListWidget,
    QListWidgetItem,
    QMainWindow,
    QMenu,
    QMessageBox,
    QPushButton,
    QTextBrowser,
    QTextEdit,
    QVBoxLayout,
    QWidget,
)
from PyQt6.QtGui import QKeySequence, QShortcut

from src.core.chat_backend import ChatBackend


Role = Literal["user", "assistant", "system"]


@dataclass
class SessionState:
    title: str
    messages: List[tuple[Role, str]] = field(default_factory=list)
    db_session_id: int = 0


class AsyncWorker(QThread):
    finished = pyqtSignal(str)
    error = pyqtSignal(str)

    def __init__(
        self,
        chat_backend: ChatBackend,
        prompt: str,
        session_id: int,
    ) -> None:
        super().__init__()
        self.chat_backend = chat_backend
        self.prompt = prompt
        self.session_id = session_id

    def run(self) -> None:
        try:
            result = asyncio.run(self._execute())
            self.finished.emit(result)
        except Exception as exc:
            self.error.emit(str(exc))

    async def _execute(self) -> str:
        reply, _ = await self.chat_backend.send_message(
            content=self.prompt,
            session_id=self.session_id,
        )
        return reply


class ScheduleDialog(QDialog):
    def __init__(self, schedule_items: List[str], parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setWindowTitle("日程管理")
        self.resize(420, 360)
        self.schedule_items = schedule_items

        self.list_widget = QListWidget()
        self.refresh_list()

        add_button = QPushButton("添加日程")
        remove_button = QPushButton("删除选中")
        close_button = QPushButton("关闭")

        add_button.clicked.connect(self.add_item)
        remove_button.clicked.connect(self.remove_selected)
        close_button.clicked.connect(self.accept)

        button_layout = QHBoxLayout()
        button_layout.addWidget(add_button)
        button_layout.addWidget(remove_button)
        button_layout.addStretch()
        button_layout.addWidget(close_button)

        layout = QVBoxLayout(self)
        layout.addWidget(self.list_widget)
        layout.addLayout(button_layout)

    def refresh_list(self) -> None:
        self.list_widget.clear()
        for item in self.schedule_items:
            self.list_widget.addItem(item)

    def add_item(self) -> None:
        text, ok = QInputDialog.getText(self, "新建日程", "请输入日程内容")
        if ok and text.strip():
            self.schedule_items.append(text.strip())
            self.refresh_list()

    def remove_selected(self) -> None:
        row = self.list_widget.currentRow()
        if row >= 0:
            self.schedule_items.pop(row)
            self.refresh_list()


class ChatWidget(QWidget):
    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.sessions: Dict[str, SessionState] = {}
        self.current_session_id: str = ""
        self.session_counter = 1
        self.worker: AsyncWorker | None = None
        self.schedule_items: List[str] = []
        self.is_dark_theme = False
        self.is_waiting_response = False
        self.session_panel_expanded = True

        self.backend = ChatBackend()

        self._build_ui()
        self.create_session()

    def _build_ui(self) -> None:
        main_layout = QHBoxLayout(self)
        main_layout.setContentsMargins(10, 10, 10, 10)
        main_layout.setSpacing(10)

        self.session_list = QListWidget()
        self.session_list.setMinimumWidth(200)
        self.session_list.setMaximumWidth(260)
        self.session_list.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.session_list.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.session_list.itemClicked.connect(self.on_session_switched)
        self.session_list.customContextMenuRequested.connect(self.show_session_menu)

        right_panel = QVBoxLayout()
        right_panel.setSpacing(8)

        top_toolbar = QHBoxLayout()
        self.toggle_session_button = QPushButton("折叠会话栏")
        self.toggle_session_button.clicked.connect(self.toggle_session_panel)
        self.title_label = QLabel("当前会话")
        self.loading_label = QLabel("")
        self.loading_label.setObjectName("loadingLabel")
        top_toolbar.addWidget(self.toggle_session_button)
        top_toolbar.addWidget(self.title_label)
        top_toolbar.addStretch()
        top_toolbar.addWidget(self.loading_label)

        self.chat_browser = QTextBrowser()
        self.chat_browser.setOpenExternalLinks(True)

        input_layout = QHBoxLayout()
        self.input_edit = QTextEdit()
        self.input_edit.setPlaceholderText("输入消息，按 Ctrl+Enter 发送")
        self.input_edit.setFixedHeight(88)
        self.send_shortcut = QShortcut(QKeySequence("Ctrl+Return"), self.input_edit)
        self.send_shortcut.activated.connect(self._on_send_clicked)

        self.send_button = QPushButton("发送")

        self.send_button.clicked.connect(self._on_send_clicked)

        input_layout.addWidget(self.input_edit, 1)
        input_layout.addWidget(self.send_button)

        right_panel.addLayout(top_toolbar)
        right_panel.addWidget(self.chat_browser, 1)
        right_panel.addLayout(input_layout)

        main_layout.addWidget(self.session_list)
        main_layout.addLayout(right_panel, 1)

    def toggle_session_panel(self) -> None:
        self.session_panel_expanded = not self.session_panel_expanded
        self.session_list.setVisible(self.session_panel_expanded)
        self.toggle_session_button.setText("折叠会话栏" if self.session_panel_expanded else "展开会话栏")

    def keyPressEvent(self, event) -> None:  # type: ignore[override]
        if event.modifiers() == Qt.KeyboardModifier.ControlModifier and event.key() == Qt.Key.Key_Return:
            self._on_send_clicked()
            return
        super().keyPressEvent(event)

    def create_session(self) -> None:
        session_id = f"session_{self.session_counter}"
        title = f"新对话 {self.session_counter}"
        self.session_counter += 1
        db_session_id = self.backend.create_session(title)
        self.sessions[session_id] = SessionState(
            title=title,
            db_session_id=db_session_id,
        )

        item = QListWidgetItem(title)
        item.setData(Qt.ItemDataRole.UserRole, session_id)
        self.session_list.addItem(item)
        self.session_list.setCurrentItem(item)
        self.switch_to_session(session_id)

    def on_session_switched(self, item: QListWidgetItem) -> None:
        session_id = item.data(Qt.ItemDataRole.UserRole)
        self.switch_to_session(session_id)

    def switch_to_session(self, session_id: str) -> None:
        if session_id not in self.sessions:
            return
        self.current_session_id = session_id
        state = self.sessions[session_id]
        self.title_label.setText(state.title)
        self.render_current_session()

    def render_current_session(self) -> None:
        self.chat_browser.clear()
        state = self.sessions[self.current_session_id]
        if state.db_session_id:
            db_messages = self.backend.get_history(state.db_session_id)
            for msg in db_messages:
                self.append_message(msg.role, msg.content, persist=False)
        else:
            for role, content in state.messages:
                self.append_message(role, content, persist=False)

    def show_session_menu(self, pos) -> None:
        item = self.session_list.itemAt(pos)
        if item is None:
            return
        session_id = item.data(Qt.ItemDataRole.UserRole)

        menu = QMenu(self)
        rename_action = QAction("重命名", self)
        delete_action = QAction("删除", self)
        clear_action = QAction("清空历史", self)

        rename_action.triggered.connect(lambda: self.rename_session(session_id, item))
        delete_action.triggered.connect(lambda: self.delete_session(session_id))
        clear_action.triggered.connect(lambda: self.clear_history(session_id))

        menu.addAction(rename_action)
        menu.addAction(delete_action)
        menu.addAction(clear_action)
        menu.exec(self.session_list.mapToGlobal(pos))

    def rename_session(self, session_id: str, item: QListWidgetItem) -> None:
        state = self.sessions.get(session_id)
        if state is None:
            return
        text, ok = QInputDialog.getText(self, "重命名会话", "新名称", text=state.title)
        if ok and text.strip():
            state.title = text.strip()
            item.setText(state.title)
            if self.current_session_id == session_id:
                self.title_label.setText(state.title)

    def delete_session(self, session_id: str) -> None:
        if len(self.sessions) == 1:
            QMessageBox.information(self, "提示", "至少保留一个会话")
            return

        state = self.sessions.get(session_id)
        if state and state.db_session_id:
            self.backend.delete_session(state.db_session_id)

        for row in range(self.session_list.count()):
            item = self.session_list.item(row)
            if item.data(Qt.ItemDataRole.UserRole) == session_id:
                self.session_list.takeItem(row)
                break

        self.sessions.pop(session_id, None)
        if self.current_session_id == session_id:
            first_item = self.session_list.item(0)
            if first_item:
                self.session_list.setCurrentItem(first_item)
                self.switch_to_session(first_item.data(Qt.ItemDataRole.UserRole))

    def clear_history(self, session_id: str | None = None) -> None:
        if isinstance(session_id, bool):
            session_id = None
        sid = session_id or self.current_session_id
        state = self.sessions.get(sid)
        if state is None:
            return
        state.messages.clear()
        if state.db_session_id:
            self.backend.clear_history(state.db_session_id)
        if sid == self.current_session_id:
            self.chat_browser.clear()

    @staticmethod
    def _escape_html(text: str) -> str:
        return html_module.escape(text).replace("\n", "<br/>")

    def append_message(self, role: Role, content: str, persist: bool = True) -> None:
        if role == "user":
            bg = "#4F46E5"
            text_color = "#ffffff"
            align = "right"
            cell_color = "#E0E7FF"
        elif role == "assistant":
            bg = "#F8FAFC"
            text_color = "#111827"
            align = "left"
            cell_color = "#EEF2FF"
        else:
            bg = "#F3F4F6"
            text_color = "#374151"
            align = "left"
            cell_color = "#F3F4F6"

        escaped = self._escape_html(content)
        html = (
            f"<table width='100%' style='margin:6px 0; border-collapse:collapse;'>"
            f"<tr>"
            f"<td align='{align}' style='padding:0 8px;'>"
            f"<div style='"
            f"display:inline-block; "
            f"max-width:75%; "
            f"background:{cell_color}; "
            f"border-radius:12px; "
            f"padding:10px 14px; "
            f"border:1px solid {'#C7D2FE' if role=='user' else '#E5E7EB'};'>"
            f"<div style='color:{text_color}; font-family:\"Microsoft YaHei UI\",sans-serif; "
            f"font-size:14px; line-height:1.6; white-space:pre-wrap; word-break:break-word;'>"
            f"{escaped}"
            f"</div>"
            f"</div>"
            f"</td></tr></table>"
        )
        self.chat_browser.append(html)
        self.chat_browser.verticalScrollBar().setValue(
            self.chat_browser.verticalScrollBar().maximum()
        )

        if persist:
            self.sessions[self.current_session_id].messages.append((role, content))

    def set_busy(self, busy: bool, text: str = "") -> None:
        self.input_edit.setDisabled(busy)
        self.send_button.setDisabled(busy)
        self.session_list.setDisabled(busy)
        self.loading_label.setText(text if busy else "")

    def _on_send_clicked(self) -> None:
        content = self.input_edit.toPlainText().strip()
        if not content or self.is_waiting_response:
            return

        self._send_message(content)

    def _send_message(self, content: str) -> None:
        self.set_busy(True, "思考中...")
        self.is_waiting_response = True

        self.append_message("user", content)
        self.input_edit.clear()

        state = self.sessions[self.current_session_id]
        self.worker = AsyncWorker(
            chat_backend=self.backend,
            prompt=content,
            session_id=state.db_session_id,
        )
        self.worker.finished.connect(self._on_reply_received)
        self.worker.error.connect(self._on_error)
        self.worker.start()

    def _on_reply_received(self, content: str) -> None:
        self.append_message("assistant", content)
        self._restore_input()

    def _on_error(self, err: str) -> None:
        self.append_message("system", f"请求失败: {err}")
        self._restore_input()

    def _restore_input(self) -> None:
        self.set_busy(False)
        self.is_waiting_response = False
        self.worker = None

    def open_schedule_dialog(self) -> None:
        dialog = ScheduleDialog(self.schedule_items, self)
        dialog.exec()

    def export_schedule_files(self) -> None:
        if not self.schedule_items:
            QMessageBox.information(self, "提示", "当前没有可导出的日程")
            return

        target_dir = QFileDialog.getExistingDirectory(self, "选择导出目录")
        if not target_dir:
            return

        txt_path = Path(target_dir) / "schedule.txt"
        md_path = Path(target_dir) / "schedule.md"

        txt_content = "\n".join(self.schedule_items)
        md_lines = ["# 日程列表", ""]
        md_lines.extend([f"- {item}" for item in self.schedule_items])
        md_content = "\n".join(md_lines)

        txt_path.write_text(txt_content, encoding="utf-8")
        md_path.write_text(md_content, encoding="utf-8")
        QMessageBox.information(self, "导出完成", f"已导出:\n{txt_path}\n{md_path}")


class MainWindow(QMainWindow):
    def __init__(self) -> None:
        super().__init__()
        self.setWindowTitle("Deskmate 智能桌面助手")
        self.resize(1320, 820)

        self.chat_widget = ChatWidget(self)
        self.last_pet_reply_index = -1

        root = QWidget()
        root_layout = QHBoxLayout(root)
        root_layout.setContentsMargins(0, 0, 0, 0)
        root_layout.setSpacing(0)

        left_panel = self._build_left_panel()
        left_panel.setFixedWidth(380)

        root_layout.addWidget(left_panel)
        root_layout.addWidget(self.chat_widget, 1)
        self.setCentralWidget(root)

        self.apply_theme("light")

    @staticmethod
    def _natural_sort_key(path: Path) -> List[int | str]:
        parts = re.split(r"(\d+)", path.name)
        return [int(part) if part.isdigit() else part.lower() for part in parts]

    def _build_left_panel(self) -> QWidget:
        panel = QWidget()
        panel.setObjectName("leftPanel")
        layout = QVBoxLayout(panel)
        layout.setContentsMargins(14, 14, 14, 14)
        layout.setSpacing(12)

        pet_title = QLabel("桌宠互动")
        pet_title.setObjectName("petTitle")

        self.pet_label = QLabel()
        self.pet_label.setObjectName("petLabel")
        self.pet_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        # 桌宠显示区固定为 4:3。
        self.pet_label.setFixedSize(336, 252)
        self.pet_label.setCursor(Qt.CursorShape.PointingHandCursor)

        self.pet_frames = self._load_pet_frames()
        self.scaled_pet_frames: List[QPixmap] = []
        self.pet_index = 0
        self.pet_direction = 1
        self._refresh_scaled_pet_frames()
        self._update_pet_frame()

        self.pet_timer = QTimer(self)
        self.pet_timer.setInterval(180)
        self.pet_timer.timeout.connect(self._next_pet_frame)
        self.pet_timer.start()

        self.pet_label.mousePressEvent = self.on_pet_clicked  # type: ignore[assignment]

        button_box = QVBoxLayout()
        button_box.setSpacing(10)

        schedule_btn = QPushButton("日程管理")
        new_chat_btn = QPushButton("新建对话")
        clear_chat_btn = QPushButton("清空当前对话")
        theme_btn = QPushButton("切换主题/换肤")
        export_btn = QPushButton("导出日程为 TXT + MD")

        schedule_btn.clicked.connect(self.chat_widget.open_schedule_dialog)
        new_chat_btn.clicked.connect(self.chat_widget.create_session)
        clear_chat_btn.clicked.connect(lambda: self.chat_widget.clear_history())
        theme_btn.clicked.connect(self.toggle_theme)
        export_btn.clicked.connect(self.chat_widget.export_schedule_files)

        for btn in [schedule_btn, new_chat_btn, clear_chat_btn, theme_btn, export_btn]:
            btn.setMinimumHeight(42)
            button_box.addWidget(btn)

        button_box.addStretch()

        layout.addWidget(pet_title)
        layout.addWidget(self.pet_label)
        layout.addLayout(button_box)
        return panel

    def resizeEvent(self, event) -> None:
        super().resizeEvent(event)
        if hasattr(self, "pet_label") and self.pet_label.width() > 0:
            self._refresh_scaled_pet_frames()

    def _load_pet_frames(self) -> List[QPixmap]:
        pet_dir = Path("src/asset/default")
        frame_paths: List[Path] = []
        if pet_dir.exists():
            frame_paths = sorted(pet_dir.glob("*.png"), key=self._natural_sort_key)[:27]

        frames: List[QPixmap] = []
        for idx, frame_path in enumerate(frame_paths, start=1):
            if frame_path.exists():
                pixmap = QPixmap(str(frame_path))
                if not pixmap.isNull():
                    frames.append(pixmap)
        if frames:
            if len(frames) >= 27:
                return frames

            for idx in range(len(frames) + 1, 28):
                placeholder = QPixmap(400, 300)
                placeholder.fill(QColor("#D6E4FF"))
                painter = QPainter(placeholder)
                painter.setPen(QColor("#334155"))
                painter.drawText(placeholder.rect(), Qt.AlignmentFlag.AlignCenter, f"PET\\nFRAME {idx}")
                painter.end()
                frames.append(placeholder)
            return frames

        # 未检测到真实帧时，生成占位帧方便后续替换资源。
        for idx in range(1, 28):
            placeholder = QPixmap(400, 300)
            placeholder.fill(QColor("#D6E4FF"))
            painter = QPainter(placeholder)
            painter.setPen(QColor("#334155"))
            painter.drawText(placeholder.rect(), Qt.AlignmentFlag.AlignCenter, f"PET\\nFRAME {idx}")
            painter.end()
            frames.append(placeholder)

        return frames

    def _refresh_scaled_pet_frames(self) -> None:
        target_size = self.pet_label.size()
        if target_size.width() <= 0 or target_size.height() <= 0:
            return
        self.scaled_pet_frames = [
            frame.scaled(
                target_size.width(),
                target_size.height(),
                Qt.AspectRatioMode.KeepAspectRatio,
                Qt.TransformationMode.SmoothTransformation,
            )
            for frame in self.pet_frames
        ]

    def _next_pet_frame(self) -> None:
        if len(self.pet_frames) <= 1:
            self._update_pet_frame()
            return

        self.pet_index += self.pet_direction
        if self.pet_index >= len(self.pet_frames) - 1:
            self.pet_index = len(self.pet_frames) - 1
            self.pet_direction = -1
        elif self.pet_index <= 0:
            self.pet_index = 0
            self.pet_direction = 1
        self._update_pet_frame()

    def _update_pet_frame(self) -> None:
        if not self.scaled_pet_frames or self.pet_index >= len(self.scaled_pet_frames):
            if self.pet_label.width() > 0 and self.pet_label.height() > 0:
                self._refresh_scaled_pet_frames()
            if not self.scaled_pet_frames:
                return
        pixmap = self.scaled_pet_frames[self.pet_index]
        self.pet_label.setPixmap(pixmap)

    def on_pet_clicked(self, _event) -> None:
        replies = [
            "桌宠: 主人今天也很努力呢，继续冲刺吧。",
            "桌宠: 要不要先喝口水再继续聊天？",
            "桌宠: 我已经帮你守着窗口啦。",
            "桌宠: 点我有惊喜，今天的效率 +10%。",
            "桌宠: 你的灵感正在加载中，请稍等 1 秒钟。",
            "桌宠: 如果你愿意，我可以当你的摸鱼监督员。",
            "桌宠: 先完成一个小目标，再奖励自己一首歌吧。",
            "桌宠: 这条消息附带 buff，专注力 +20%。",
            "桌宠: 我在，随时可以陪你继续聊。",
            "桌宠: 你负责发问，我负责卖萌和打气。",
        ]
        if len(replies) == 1:
            index = 0
        else:
            candidate_indices = [i for i in range(len(replies)) if i != self.last_pet_reply_index]
            index = random.choice(candidate_indices)
        self.last_pet_reply_index = index
        self.chat_widget.append_message("assistant", replies[index])

    def toggle_theme(self) -> None:
        self.chat_widget.is_dark_theme = not self.chat_widget.is_dark_theme
        self.apply_theme("dark" if self.chat_widget.is_dark_theme else "light")

    def apply_theme(self, theme: Literal["light", "dark"]) -> None:
        light_qss = """
        QWidget { background-color: #F5F7FB; color: #1E293B; font-family: Microsoft YaHei UI; }
        #leftPanel { background-color: #E9EEF8; border-right: 1px solid #D0D8EA; }
        #petTitle { font-size: 16px; font-weight: 700; }
        #petLabel { background-color: #FFFFFF; border: 1px solid #D5DEEF; border-radius: 12px; }
        QListWidget, QTextBrowser, QTextEdit {
            background-color: #FFFFFF;
            border: 1px solid #CFD8EA;
            border-radius: 10px;
            padding: 6px;
        }
        QPushButton {
            background-color: #2563EB;
            color: #FFFFFF;
            border: none;
            border-radius: 8px;
            padding: 8px 12px;
        }
        QPushButton:hover { background-color: #1D4ED8; }
        QPushButton:disabled { background-color: #94A3B8; }
        #loadingLabel { color: #2563EB; font-weight: 600; }
        """

        dark_qss = """
        QWidget { background-color: #0F172A; color: #E2E8F0; font-family: Microsoft YaHei UI; }
        #leftPanel { background-color: #111B33; border-right: 1px solid #27344F; }
        #petTitle { font-size: 16px; font-weight: 700; color: #F8FAFC; }
        #petLabel { background-color: #1E293B; border: 1px solid #334155; border-radius: 12px; }
        QListWidget, QTextBrowser, QTextEdit {
            background-color: #111827;
            border: 1px solid #334155;
            border-radius: 10px;
            padding: 6px;
            color: #E2E8F0;
        }
        QPushButton {
            background-color: #3B82F6;
            color: #F8FAFC;
            border: none;
            border-radius: 8px;
            padding: 8px 12px;
        }
        QPushButton:hover { background-color: #2563EB; }
        QPushButton:disabled { background-color: #475569; color: #CBD5E1; }
        #loadingLabel { color: #93C5FD; font-weight: 600; }
        """

        QApplication.instance().setStyleSheet(dark_qss if theme == "dark" else light_qss)


def run_app() -> None:
    app = QApplication([])
    app.setWindowIcon(QIcon())
    window = MainWindow()
    window.show()
    app.exec()


if __name__ == "__main__":
    run_app()
