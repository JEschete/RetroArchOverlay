from __future__ import annotations

from collections import deque

from PySide6.QtCore import QObject, QTimer, Signal
from PySide6.QtGui import QAccessible, QAccessibleEvent, QColor, QPalette
from PySide6.QtWidgets import QFrame, QLabel, QVBoxLayout, QWidget

from ...app.notifications import AlertNotification
from ..theme import THEME_PALETTES, resolve_theme


class QtToastQueue(QObject):
    notification_shown = Signal(object)

    def __init__(
        self,
        owner: QWidget,
        *,
        duration_ms: int = 3_500,
        theme: str = "light",
    ) -> None:
        super().__init__(owner)
        if duration_ms <= 0:
            raise ValueError("Toast duration must be positive")
        self._owner = owner
        self._queue: deque[AlertNotification] = deque()
        self._active: AlertNotification | None = None
        self._frame = QFrame(owner)
        self._frame.setObjectName("alertToast")
        self._frame.setFrameShape(QFrame.Shape.StyledPanel)
        self._frame.setAutoFillBackground(True)
        layout = QVBoxLayout(self._frame)
        layout.setContentsMargins(12, 8, 12, 8)
        layout.setSpacing(2)
        self.title_label = QLabel(self._frame)
        self.title_label.setObjectName("alertToastTitle")
        self.title_label.setWordWrap(True)
        self.detail_label = QLabel(self._frame)
        self.detail_label.setObjectName("alertToastDetail")
        self.detail_label.setWordWrap(True)
        layout.addWidget(self.title_label)
        layout.addWidget(self.detail_label)
        self._frame.hide()
        self._timer = QTimer(self)
        self._timer.setSingleShot(True)
        self._timer.setInterval(duration_ms)
        self._timer.timeout.connect(self.dismiss)
        self.set_theme(theme)

    @property
    def active(self) -> AlertNotification | None:
        return self._active

    @property
    def pending_count(self) -> int:
        return len(self._queue)

    @property
    def visible(self) -> bool:
        return self._frame.isVisible()

    def enqueue(self, notifications: tuple[AlertNotification, ...]) -> None:
        self._queue.extend(notifications)
        if self._active is None:
            self._show_next()

    def dismiss(self) -> None:
        self._timer.stop()
        self._frame.hide()
        self._active = None
        self._show_next()

    def clear(self) -> None:
        self._timer.stop()
        self._queue.clear()
        self._active = None
        self._frame.hide()

    def close(self) -> None:
        self.clear()

    def reposition(self) -> None:
        if not self._frame.isVisible():
            return
        maximum_width = max(220, min(360, self._owner.width() - 16))
        self.title_label.setMaximumWidth(maximum_width - 24)
        self.detail_label.setMaximumWidth(maximum_width - 24)
        self._frame.adjustSize()
        self._frame.move(
            max(8, self._owner.width() - self._frame.width() - 8),
            8,
        )
        self._frame.raise_()

    def set_theme(self, preference: str) -> str:
        name = resolve_theme(preference)
        colors = THEME_PALETTES[name]
        palette = self._frame.palette()
        palette.setColor(palette.ColorRole.Window, QColor(colors["alert_background"]))
        palette.setColor(
            palette.ColorRole.WindowText,
            QColor(colors["alert_foreground"]),
        )
        self._frame.setPalette(palette)
        self.title_label.setPalette(palette)
        detail_palette = QPalette(palette)
        detail_palette.setColor(
            detail_palette.ColorRole.WindowText,
            QColor(colors["foreground"]),
        )
        self.detail_label.setPalette(detail_palette)
        return name

    def _show_next(self) -> None:
        if not self._queue:
            return
        notification = self._queue.popleft()
        self._active = notification
        self.title_label.setText(notification.title.upper())
        self.detail_label.setText(notification.detail)
        self.detail_label.setVisible(bool(notification.detail))
        accessible = notification.title + (
            f": {notification.detail}" if notification.detail else ""
        )
        self._frame.setAccessibleName(accessible)
        self._frame.show()
        self.reposition()
        QAccessible.updateAccessibility(
            QAccessibleEvent(self._frame, QAccessible.Event.Alert)
        )
        self.notification_shown.emit(notification)
        self._timer.start()