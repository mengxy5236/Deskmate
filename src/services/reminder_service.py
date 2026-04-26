from __future__ import annotations

import asyncio
import os
import re
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Callable, Optional

from src.core.database import Database, Reminder
from src.modules.scheduler import ReminderScheduler
from src.modules.weather import get_weather


@dataclass
class ReminderCommandResult:
    handled: bool
    reply: str = ""


class ReminderService:
    """Owns reminder-related use cases, parsing, and scheduling."""

    TODAY_KEYWORDS = [
        "\u4eca\u65e5\u63d0\u9192",
        "\u4eca\u5929\u63d0\u9192",
        "\u67e5\u770b\u4eca\u65e5\u63d0\u9192",
        "\u4eca\u5929\u6709\u4ec0\u4e48\u63d0\u9192",
        "\u4eca\u65e5\u5f85\u529e",
        "\u4eca\u5929\u5f85\u529e",
    ]
    REMIND_WORD = "\u63d0\u9192\u6211"
    DATETIME_FORMAT = "%Y-%m-%d %H:%M:%S"
    DEFAULT_CITY = os.getenv("WEA_DEFAULT_CITY", "\u5929\u6d25")
    OUTDOOR_KEYWORDS = [
        "\u51fa\u95e8",
        "\u4e0a\u73ed",
        "\u901a\u52e4",
        "\u4e0a\u5b66",
        "\u5b66\u6821",
        "\u5f00\u4f1a",
        "\u673a\u573a",
        "\u9ad8\u94c1",
        "\u706b\u8f66",
        "\u89c1\u5ba2\u6237",
        "\u51fa\u5dee",
    ]

    def __init__(self, db: Database, on_trigger: Callable[[Reminder], None]) -> None:
        self._db = db
        self._scheduler = ReminderScheduler(db=db, on_trigger=on_trigger)

    def start(self) -> None:
        self._scheduler.start()

    def shutdown(self) -> None:
        self._scheduler.shutdown()

    def list_reminders(self, include_cancelled: bool = False) -> list[Reminder]:
        return self._db.list_reminders(include_cancelled=include_cancelled)

    def create_reminder(self, title: str, content: str, remind_at: datetime) -> Reminder:
        return self._scheduler.create_reminder(title=title, content=content, remind_at=remind_at)

    def create_test_reminder(self, delay_seconds: int = 10) -> Reminder:
        remind_at = datetime.now() + timedelta(seconds=delay_seconds)
        return self.create_reminder(
            title="\u6d4b\u8bd5\u63d0\u9192",
            content=f"\u8fd9\u662f\u4e00\u6761 {delay_seconds} \u79d2\u540e\u7684\u6d4b\u8bd5\u63d0\u9192\u3002",
            remind_at=remind_at,
        )

    def snooze_reminder(self, reminder_id: int, minutes: int = 10) -> Optional[Reminder]:
        return self._scheduler.snooze_reminder(reminder_id, minutes=minutes)

    def complete_reminder(self, reminder_id: int) -> None:
        self._scheduler.complete_reminder(reminder_id)

    def cancel_reminder(self, reminder_id: int) -> None:
        self._scheduler.cancel_reminder(reminder_id)

    def handle_chat_command(self, content: str) -> ReminderCommandResult:
        text = content.strip()

        if any(keyword in text for keyword in self.TODAY_KEYWORDS):
            return ReminderCommandResult(True, self._build_today_reminders_text())

        if self.REMIND_WORD not in text:
            return ReminderCommandResult(False)

        remind_at = self._parse_chat_time(text)
        if remind_at is None:
            return ReminderCommandResult(False)
        if remind_at <= datetime.now():
            return ReminderCommandResult(
                True,
                "\u8fd9\u4e2a\u63d0\u9192\u65f6\u95f4\u5df2\u7ecf\u8fc7\u53bb\u4e86\uff0c\u8bf7\u6362\u4e00\u4e2a\u672a\u6765\u65f6\u95f4\u3002",
            )

        title = text.split(self.REMIND_WORD, 1)[1].strip(" \u3001\uff0c\u3002")
        if not title:
            return ReminderCommandResult(
                True,
                "\u6211\u77e5\u9053\u4f60\u60f3\u8bbe\u63d0\u9192\uff0c\u4f46\u8fd8\u6ca1\u6709\u63d0\u9192\u5185\u5bb9\u3002",
            )

        reminder = self.create_reminder(title=title, content="", remind_at=remind_at)
        return ReminderCommandResult(
            True,
            f"\u5df2\u521b\u5efa\u63d0\u9192\uff1a{reminder.title}\n\u65f6\u95f4\uff1a{reminder.remind_at}",
        )

    def validate_manual_reminder(self, title: str, remind_at: datetime) -> Optional[str]:
        if not title.strip():
            return "\u8bf7\u586b\u5199\u63d0\u9192\u6807\u9898\u3002"
        if remind_at <= datetime.now():
            return "\u63d0\u9192\u65f6\u95f4\u9700\u8981\u665a\u4e8e\u5f53\u524d\u65f6\u95f4\u3002"
        return None

    def format_created_reply(self, reminder: Reminder) -> str:
        return f"\u5df2\u521b\u5efa\u63d0\u9192\uff1a{reminder.title}\n\u65f6\u95f4\uff1a{reminder.remind_at}"

    def format_snoozed_reply(self, reminder: Reminder, minutes: int = 10) -> str:
        return (
            f"\u63d0\u9192\u5df2\u7a0d\u540e {minutes} \u5206\u949f\uff1a{reminder.title}\n"
            f"\u65b0\u7684\u65f6\u95f4\uff1a{reminder.remind_at}"
        )

    def format_trigger_message(self, reminder: Reminder) -> str:
        text = f"\u63d0\u9192\uff1a{reminder.title}"
        if reminder.content:
            text += f"\n{reminder.content}"
        weather_tip = self._build_weather_tip(reminder)
        if weather_tip:
            text += f"\n{weather_tip}"
        return text

    def format_trigger_notification(self, reminder: Reminder) -> str:
        lines = [reminder.title]
        if reminder.content:
            lines.append(reminder.content)
        weather_tip = self._build_weather_tip(reminder)
        if weather_tip:
            lines.append(weather_tip)
        return "\n".join(lines)

    def _build_today_reminders_text(self) -> str:
        today = datetime.now().date()
        reminders = [
            reminder
            for reminder in self.list_reminders()
            if datetime.strptime(reminder.remind_at, self.DATETIME_FORMAT).date() == today
            and reminder.status in {"pending", "triggered"}
        ]
        if not reminders:
            return "\u4eca\u5929\u8fd8\u6ca1\u6709\u63d0\u9192\u3002"

        lines = ["\u4eca\u5929\u7684\u63d0\u9192\uff1a"]
        for index, reminder in enumerate(sorted(reminders, key=lambda item: item.remind_at), start=1):
            lines.append(f"{index}. {reminder.title}  {reminder.remind_at[11:16]}")
        return "\n".join(lines)

    def _parse_chat_time(self, text: str) -> datetime | None:
        now = datetime.now()

        relative = re.search(
            r"(\d+)\s*(\u79d2\u949f|\u79d2|\u5206\u949f|\u5206|\u5c0f\u65f6)\s*\u540e\u63d0\u9192\u6211",
            text,
        )
        if relative:
            value = int(relative.group(1))
            unit = relative.group(2)
            if "\u79d2" in unit:
                return now + timedelta(seconds=value)
            if "\u5206" in unit:
                return now + timedelta(minutes=value)
            return now + timedelta(hours=value)

        absolute = re.search(
            r"(\u4eca\u5929|\u4eca\u65e5|\u4eca\u665a|\u660e\u5929)\s*(\d{1,2})(?:[:\u70b9\u65f6](\d{1,2}))?\s*\u63d0\u9192\u6211",
            text,
        )
        if not absolute:
            return None

        day_word = absolute.group(1)
        hour = int(absolute.group(2))
        minute = int(absolute.group(3) or 0)
        target = now + timedelta(days=1) if day_word == "\u660e\u5929" else now
        if day_word == "\u4eca\u665a" and hour < 12:
            hour += 12
        return target.replace(hour=hour, minute=minute, second=0, microsecond=0)

    def _build_weather_tip(self, reminder: Reminder) -> str:
        combined = f"{reminder.title} {reminder.content}".strip()
        if not any(keyword in combined for keyword in self.OUTDOOR_KEYWORDS):
            return ""

        weather_text = self._fetch_weather_text(self.DEFAULT_CITY)
        if not weather_text or "\u5929\u6c14\u63a5\u53e3" in weather_text:
            return ""

        tips: list[str] = []
        if "\u96e8" in weather_text or "\u9635\u96e8" in weather_text or "\u96f7" in weather_text:
            tips.append("\u5916\u9762\u53ef\u80fd\u4e0b\u96e8\uff0c\u8bb0\u5f97\u5e26\u4f1e")

        temp_matches = re.findall(r"-?\d+(?:\.\d+)?", weather_text)
        temp_c = float(temp_matches[0]) if temp_matches else None
        if temp_c is not None and temp_c >= 30:
            tips.append("\u5929\u6c14\u8f83\u70ed\uff0c\u6ce8\u610f\u9632\u6652\u8865\u6c34")
        elif temp_c is not None and temp_c <= 5:
            tips.append("\u5929\u6c14\u504f\u51b7\uff0c\u8bb0\u5f97\u591a\u7a7f\u4e00\u70b9")

        if not tips:
            return ""
        return "\u5929\u6c14\u63d0\u9192\uff1a" + "\uff1b".join(tips)

    @staticmethod
    def _fetch_weather_text(city: str) -> str:
        loop = asyncio.new_event_loop()
        try:
            asyncio.set_event_loop(loop)
            return loop.run_until_complete(get_weather(city))
        except Exception:
            return ""
        finally:
            loop.close()
