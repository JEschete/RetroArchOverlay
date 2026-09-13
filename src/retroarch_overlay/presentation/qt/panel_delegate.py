from __future__ import annotations

from collections import OrderedDict
from pathlib import Path
from typing import Mapping

from PySide6.QtCore import QModelIndex, QRect, QSize, Qt
from PySide6.QtGui import QColor, QFont, QFontMetrics, QPainter, QPixmap
from PySide6.QtWidgets import (
    QStyle,
    QStyledItemDelegate,
    QStyleOptionViewItem,
    QWidget,
)

from ...core.models import PanelChip
from ..theme import (
    THEME_PALETTES,
    accessible_text_color,
    progress_bar_color,
    resolve_theme,
)
from .panel_model import PanelRowRole


class QtIconCache:
    def __init__(self, maximum_entries: int = 128) -> None:
        if maximum_entries <= 0:
            raise ValueError("Qt icon cache size must be positive")
        self.maximum_entries = maximum_entries
        self._entries: OrderedDict[
            tuple[str, int, int, int, int], QPixmap
        ] = OrderedDict()

    @property
    def size(self) -> int:
        return len(self._entries)

    def pixmap(
        self,
        path: str,
        size: QSize,
        device_pixel_ratio: float,
    ) -> QPixmap | None:
        try:
            modified = Path(path).stat().st_mtime_ns
        except OSError:
            return None
        ratio_key = max(1, round(device_pixel_ratio * 1000))
        key = (path, modified, size.width(), size.height(), ratio_key)
        cached = self._entries.pop(key, None)
        if cached is not None:
            self._entries[key] = cached
            return cached
        source = QPixmap(path)
        if source.isNull():
            return None
        physical_size = QSize(
            max(1, round(size.width() * device_pixel_ratio)),
            max(1, round(size.height() * device_pixel_ratio)),
        )
        rendered = source.scaled(
            physical_size,
            Qt.AspectRatioMode.KeepAspectRatio,
            Qt.TransformationMode.FastTransformation,
        )
        rendered.setDevicePixelRatio(device_pixel_ratio)
        self._entries[key] = rendered
        while len(self._entries) > self.maximum_entries:
            self._entries.popitem(last=False)
        return rendered


class PanelRowDelegate(QStyledItemDelegate):
    ICON_SIZE = 24
    HORIZONTAL_MARGIN = 6
    VERTICAL_MARGIN = 4
    INDICATOR_WIDTH = 16
    PROGRESS_HEIGHT = 4

    def __init__(
        self,
        theme: str = "light",
        *,
        icon_cache: QtIconCache | None = None,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self._theme_name = ""
        self._colors: Mapping[str, str] = THEME_PALETTES["light"]
        self._icon_cache = icon_cache or QtIconCache()
        self.set_theme(theme)

    @property
    def theme_name(self) -> str:
        return self._theme_name

    @property
    def icon_cache(self) -> QtIconCache:
        return self._icon_cache

    def set_theme(self, preference: str) -> None:
        self._theme_name = resolve_theme(preference)
        self._colors = THEME_PALETTES[self._theme_name]

    def paint(
        self,
        painter: QPainter,
        option: QStyleOptionViewItem,
        index: QModelIndex,
    ) -> None:
        prepared = QStyleOptionViewItem(option)
        self.initStyleOption(prepared, index)
        prepared.text = ""
        style = prepared.widget.style() if prepared.widget is not None else None
        if style is not None:
            style.drawControl(
                QStyle.ControlElement.CE_ItemViewItem,
                prepared,
                painter,
                prepared.widget,
            )

        painter.save()
        selected = bool(prepared.state & QStyle.StateFlag.State_Selected)
        text_color = (
            prepared.palette.color(prepared.palette.ColorRole.HighlightedText).name()
            if selected
            else _emphasis_color(index, self._colors)
        )
        content = option.rect.adjusted(
            self.HORIZONTAL_MARGIN,
            self.VERTICAL_MARGIN,
            -self.HORIZONTAL_MARGIN,
            -self.VERTICAL_MARGIN,
        )
        progress = index.data(PanelRowRole.PROGRESS)
        if progress is not None:
            content.setBottom(content.bottom() - self.PROGRESS_HEIGHT - 3)

        caught = index.data(PanelRowRole.CAUGHT)
        if caught is not None:
            indicator = QRect(
                content.left(),
                content.top(),
                self.INDICATOR_WIDTH,
                content.height(),
            )
            painter.setPen(
                QColor(
                    text_color
                    if selected
                    else self._colors["success"]
                    if caught
                    else self._colors["muted"]
                )
            )
            painter.drawText(
                indicator,
                Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter,
                "✓" if caught else "○",
            )
            content.setLeft(indicator.right() + 2)

        icon_path = str(index.data(PanelRowRole.ICON_PATH) or "")
        if icon_path and option.widget is not None:
            icon = self._icon_cache.pixmap(
                icon_path,
                QSize(self.ICON_SIZE, self.ICON_SIZE),
                option.widget.devicePixelRatioF(),
            )
            if icon is not None:
                icon_rect = QRect(
                    content.left(),
                    content.top() + max(0, (content.height() - self.ICON_SIZE) // 2),
                    self.ICON_SIZE,
                    self.ICON_SIZE,
                )
                painter.drawPixmap(icon_rect, icon)
                content.setLeft(icon_rect.right() + 5)

        chips = tuple(index.data(PanelRowRole.CHIPS) or ())
        chip_font = QFont(option.font)
        chip_font.setPointSizeF(max(7.0, chip_font.pointSizeF() - 2.0))
        chip_font.setBold(True)
        chip_metrics = QFontMetrics(chip_font)
        chip_right = content.right()
        for chip in reversed(chips):
            if not isinstance(chip, PanelChip):
                continue
            width = chip_metrics.horizontalAdvance(chip.text) + 12
            chip_rect = QRect(
                chip_right - width + 1,
                content.top() + max(0, (content.height() - chip_metrics.height() - 6) // 2),
                width,
                chip_metrics.height() + 6,
            )
            background = _normalized_color(chip.background, self._colors["muted"])
            requested_foreground = _normalized_color(
                chip.foreground,
                self._colors["header_foreground"],
            )
            foreground = accessible_text_color(background, requested_foreground)
            painter.setPen(Qt.PenStyle.NoPen)
            painter.setBrush(QColor(background))
            painter.drawRoundedRect(chip_rect, 3, 3)
            painter.setFont(chip_font)
            painter.setPen(QColor(foreground))
            painter.drawText(chip_rect, Qt.AlignmentFlag.AlignCenter, chip.text)
            chip_right = chip_rect.left() - 4
        content.setRight(max(content.left(), chip_right))

        text = str(index.data(Qt.ItemDataRole.DisplayRole) or "")
        text_font = QFont(option.font)
        if _is_heading(text, str(index.data(PanelRowRole.EMPHASIS) or "")):
            text_font.setBold(True)
        painter.setFont(text_font)
        painter.setPen(QColor(text_color))
        painter.drawText(
            content,
            Qt.AlignmentFlag.AlignLeft
            | Qt.AlignmentFlag.AlignVCenter
            | Qt.TextFlag.TextWordWrap,
            text,
        )

        if progress is not None:
            fraction = max(0.0, min(1.0, float(progress)))
            track = QRect(
                option.rect.left() + self.HORIZONTAL_MARGIN,
                option.rect.bottom() - self.VERTICAL_MARGIN - self.PROGRESS_HEIGHT + 1,
                max(0, option.rect.width() - self.HORIZONTAL_MARGIN * 2),
                self.PROGRESS_HEIGHT,
            )
            painter.fillRect(track, QColor(self._colors["track"]))
            fill = QRect(track)
            fill.setWidth(round(track.width() * fraction))
            requested_progress = progress_bar_color(
                fraction,
                self._colors,
                str(index.data(PanelRowRole.PROGRESS_COLOR) or ""),
            )
            painter.fillRect(
                fill,
                QColor(_normalized_color(requested_progress, self._colors["accent"])),
            )
        painter.restore()

    def sizeHint(
        self,
        option: QStyleOptionViewItem,
        index: QModelIndex,
    ) -> QSize:
        text = str(index.data(Qt.ItemDataRole.DisplayRole) or "")
        font = QFont(option.font)
        if _is_heading(text, str(index.data(PanelRowRole.EMPHASIS) or "")):
            font.setBold(True)
        metrics = QFontMetrics(font)
        width = option.rect.width()
        if width <= 0 and option.widget is not None:
            width = option.widget.width()
        width = max(120, width) - self.HORIZONTAL_MARGIN * 2
        if index.data(PanelRowRole.CAUGHT) is not None:
            width -= self.INDICATOR_WIDTH + 2
        if index.data(PanelRowRole.ICON_PATH):
            width -= self.ICON_SIZE + 5
        chips = tuple(index.data(PanelRowRole.CHIPS) or ())
        chip_font = QFont(font)
        chip_font.setPointSizeF(max(7.0, chip_font.pointSizeF() - 2.0))
        chip_metrics = QFontMetrics(chip_font)
        width -= sum(chip_metrics.horizontalAdvance(chip.text) + 16 for chip in chips)
        text_rect = metrics.boundingRect(
            QRect(0, 0, max(40, width), 10_000),
            Qt.TextFlag.TextWordWrap,
            text,
        )
        height = max(metrics.height(), text_rect.height(), self.ICON_SIZE if index.data(PanelRowRole.ICON_PATH) else 0)
        if index.data(PanelRowRole.PROGRESS) is not None:
            height += self.PROGRESS_HEIGHT + 3
        return QSize(max(120, option.rect.width()), height + self.VERTICAL_MARGIN * 2)


def _is_heading(text: str, emphasis: str) -> bool:
    return emphasis == "heading" or (
        not emphasis and text.isupper() and len(text) > 3
    )


def _emphasis_color(index: QModelIndex, colors: Mapping[str, str]) -> str:
    emphasis = str(index.data(PanelRowRole.EMPHASIS) or "")
    if _is_heading(str(index.data(Qt.ItemDataRole.DisplayRole) or ""), emphasis):
        return colors["accent"]
    return {
        "muted": colors["muted"],
        "success": colors["success"],
        "warning": colors["warning"],
        "danger": colors["danger"],
    }.get(emphasis, colors["foreground"])


def _normalized_color(value: str, fallback: str) -> str:
    color = QColor(value)
    return color.name() if color.isValid() else fallback