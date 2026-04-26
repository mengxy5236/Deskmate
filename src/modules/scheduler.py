from __future__ import annotations

import logging
from datetime import datetime, timedelta
from typing import Callable, Optional

from apscheduler.executors.pool import ThreadPoolExecutor
from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.triggers.date import DateTrigger

from src.core.database import Database, Reminder

logger = logging.getLogger(__name__)


class ReminderScheduler:
    """提醒调度器，负责恢复和触发单次提醒。"""

    def __init__(
        self,
        db: Database,
        on_trigger: Callable[[Reminder], None],
    ) -> None:
        self._db = db
        self._on_trigger = on_trigger
        self._scheduler = BackgroundScheduler(
            executors={"default": ThreadPoolExecutor(4)},
            job_defaults={"coalesce": False, "max_instances": 1},
        )

    def start(self) -> None:
        if not self._scheduler.running:
            self._scheduler.start()
        self.restore_pending_reminders()

    def shutdown(self) -> None:
        if self._scheduler.running:
            self._scheduler.shutdown(wait=False)

    def restore_pending_reminders(self) -> None:
        for reminder in self._db.get_pending_reminders():
            self.schedule_existing(reminder)

    def create_reminder(
        self,
        title: str,
        remind_at: datetime,
        content: str = "",
    ) -> Reminder:
        reminder_id = self._db.create_reminder(
            title=title,
            content=content,
            remind_at=remind_at.strftime("%Y-%m-%d %H:%M:%S"),
        )
        reminder = self._db.get_reminder(reminder_id)
        if reminder is None:
            raise RuntimeError("Failed to load created reminder")
        self.schedule_existing(reminder)
        return reminder

    def schedule_existing(self, reminder: Reminder) -> None:
        run_at = datetime.strptime(reminder.remind_at, "%Y-%m-%d %H:%M:%S")
        if run_at <= datetime.now():
            self._fire_reminder(reminder.id)
            return

        self._scheduler.add_job(
            self._fire_reminder,
            trigger=DateTrigger(run_date=run_at),
            args=[reminder.id],
            id=self._job_id(reminder.id),
            replace_existing=True,
        )

    def cancel_reminder(self, reminder_id: int) -> None:
        self._db.cancel_reminder(reminder_id)
        self._remove_job(reminder_id)

    def complete_reminder(self, reminder_id: int) -> None:
        self._db.complete_reminder(reminder_id)
        self._remove_job(reminder_id)

    def snooze_reminder(self, reminder_id: int, minutes: int = 10) -> Optional[Reminder]:
        reminder = self._db.get_reminder(reminder_id)
        if reminder is None:
            return None

        remind_at = datetime.now() + timedelta(minutes=minutes)
        self._db.reschedule_reminder(
            reminder_id,
            remind_at.strftime("%Y-%m-%d %H:%M:%S"),
        )
        latest = self._db.get_reminder(reminder_id)
        if latest is None:
            return None
        self.schedule_existing(latest)
        return latest

    def _remove_job(self, reminder_id: int) -> None:
        try:
            self._scheduler.remove_job(self._job_id(reminder_id))
        except Exception as exc:
            logger.debug("Failed to remove reminder job %s: %s", reminder_id, exc)

    def _job_id(self, reminder_id: int) -> str:
        return f"reminder:{reminder_id}"

    def _fire_reminder(self, reminder_id: int) -> None:
        reminder = self._db.get_reminder(reminder_id)
        if reminder is None or reminder.status != "pending":
            return

        self._db.mark_reminder_triggered(reminder_id)
        latest = self._db.get_reminder(reminder_id)
        if latest is not None:
            self._on_trigger(latest)
