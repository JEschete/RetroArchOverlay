from __future__ import annotations

from dataclasses import replace

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QVBoxLayout, QWidget

from ...core.models import OverlaySnapshot, ScreenRect
from ...core.presentation import compact_secondary_sections
from .panel_document_view import PanelDocumentView
from .theme import apply_qt_theme


class QtSecondaryPanelWindow(QWidget):
    def __init__(
        self,
        owner: QWidget,
        *,
        theme: str = "light",
    ) -> None:
        flags = Qt.WindowType.Tool | Qt.WindowType.FramelessWindowHint
        if owner.windowFlags() & Qt.WindowType.WindowStaysOnTopHint:
            flags |= Qt.WindowType.WindowStaysOnTopHint
        super().__init__(owner, flags)
        self.setWindowTitle("RetroArch Overlay Secondary")
        self.setAccessibleName("Secondary game information")
        self.setAttribute(Qt.WidgetAttribute.WA_ShowWithoutActivating, True)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        self.document_view = PanelDocumentView(self)
        layout.addWidget(self.document_view)
        self._theme_name = self.set_theme(theme)

    @property
    def theme_name(self) -> str:
        return self._theme_name

    def set_theme(self, preference: str) -> str:
        name = apply_qt_theme(self, preference)
        self.document_view.set_theme(name)
        self._theme_name = name
        return name

    def update_snapshot(
        self,
        snapshot: OverlaySnapshot,
        content_scope: str,
        geometry: ScreenRect,
    ) -> bool:
        sections = compact_secondary_sections(snapshot.sections)
        if not sections:
            self.hide()
            return False
        compact = replace(
            snapshot,
            sections=sections,
            supports_caught_filter=False,
            map_document=None,
            map_overlays=(),
        )
        self.document_view.set_snapshot(compact, content_scope=content_scope)
        self.document_view.set_active_role("all")
        self.setGeometry(
            geometry.left,
            geometry.top,
            geometry.width,
            geometry.height,
        )
        self.show()
        return True