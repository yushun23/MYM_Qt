"""DateEdit widget – no UTC offset issues."""

from datetime import date

from PySide6.QtCore import QDate
from PySide6.QtWidgets import QDateEdit


class SafeDateEdit(QDateEdit):
    """DateEdit that converts to/from Python date without UTC issues."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setCalendarPopup(True)
        self.setDate(QDate.currentDate())

    def get_date(self) -> date:
        qd = self.date()
        return date(qd.year(), qd.month(), qd.day())

    def set_date(self, d: date) -> None:
        self.setDate(QDate(d.year, d.month, d.day))
