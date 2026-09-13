from pathlib import Path

from PIL import Image
from PySide6.QtCore import QSize, Qt
from PySide6.QtGui import QAccessible, QColor
from PySide6.QtWidgets import QStyleOptionViewItem

from reference_documents import reference_rows
from retroarch_overlay.core.models import PanelChip, PanelRow
from retroarch_overlay.presentation.qt import PanelRowListView, QtIconCache


def _image_colors(view: PanelRowListView) -> set[str]:
    image = view.viewport().grab().toImage()
    return {
        image.pixelColor(x, y).name()
        for y in range(image.height())
        for x in range(image.width())
    }


def test_delegate_paints_semantic_progress_and_chip_colors(qtbot) -> None:
    view = PanelRowListView(reference_rows())
    view.resize(460, 520)
    view.set_theme("light")
    qtbot.addWidget(view)
    view.show()
    qtbot.waitUntil(view.isVisible)

    colors = _image_colors(view)

    assert view.row_delegate.theme_name == "light"
    assert "#123456" in colors
    assert "#334455" in colors
    assert "#ddeeff" in colors
    assert "#855700" in colors
    assert "#d8d4c8" in colors


def test_delegate_size_hint_accounts_for_wrapping_and_progress(qtbot) -> None:
    plain = PanelRow("Short")
    detailed = PanelRow(
        "A deliberately long row that wraps into multiple visual lines at a narrow width",
        progress=0.5,
    )
    view = PanelRowListView((plain, detailed))
    view.resize(180, 240)
    qtbot.addWidget(view)
    view.show()
    option = QStyleOptionViewItem()
    option.widget = view
    option.rect.setWidth(160)

    plain_size = view.row_delegate.sizeHint(option, view.row_model.index(0))
    detailed_size = view.row_delegate.sizeHint(option, view.row_model.index(1))

    assert detailed_size.height() > plain_size.height()


def test_icon_cache_is_bounded_and_preserves_device_ratio(tmp_path: Path, qapp) -> None:
    paths = []
    for index, color in enumerate(((255, 0, 0), (0, 255, 0), (0, 0, 255))):
        path = tmp_path / f"icon-{index}.png"
        Image.new("RGB", (16, 16), color).save(path)
        paths.append(path)
    cache = QtIconCache(maximum_entries=2)

    pixmaps = [
        cache.pixmap(str(path), QSize(24, 24), 1.5)
        for path in paths
    ]

    assert all(pixmap is not None for pixmap in pixmaps)
    assert cache.size == 2
    assert pixmaps[-1] is not None
    assert pixmaps[-1].devicePixelRatio() == 1.5
    assert pixmaps[-1].size() == QSize(36, 36)


def test_missing_icon_does_not_prevent_row_rendering(qtbot, tmp_path: Path) -> None:
    view = PanelRowListView((PanelRow("Still visible", icon=str(tmp_path / "missing.png")),))
    view.resize(240, 80)
    qtbot.addWidget(view)
    view.show()
    qtbot.waitUntil(view.isVisible)

    assert view.row_model.index(0).data(Qt.ItemDataRole.DisplayRole) == "Still visible"
    assert QColor(view.palette().windowText().color()).isValid()


def test_accessibility_exposes_semantic_list_item_name_and_description(qtbot) -> None:
    row = PanelRow(
        "Target",
        caught=False,
        tooltip="Found on Route 1",
        progress=0.375,
        chips=(PanelChip("WATER"),),
    )
    view = PanelRowListView((row,))
    qtbot.addWidget(view)
    view.show()
    interface = QAccessible.queryAccessibleInterface(view)

    assert interface is not None
    assert interface.role() == QAccessible.Role.List
    assert interface.text(QAccessible.Text.Name) == "Information rows"
    assert interface.childCount() == 1
    item = interface.child(0)
    assert item is not None
    assert item.role() == QAccessible.Role.ListItem
    assert item.text(QAccessible.Text.Name) == (
        "Target; not complete; progress 38 percent; tags WATER"
    )
    assert item.text(QAccessible.Text.Description) == "Found on Route 1"


def test_invalid_plugin_colors_fall_back_without_breaking_paint(qtbot) -> None:
    view = PanelRowListView(
        (
            PanelRow(
                "Invalid colors",
                progress=0.5,
                progress_color="not-a-color",
                chips=(PanelChip("BAD", "not-a-color", "also-not-a-color"),),
            ),
        )
    )
    view.resize(260, 80)
    qtbot.addWidget(view)
    view.show()

    assert not view.viewport().grab().isNull()