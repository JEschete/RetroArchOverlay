from PySide6.QtCore import QPoint, Qt
from PySide6.QtWidgets import QMainWindow

from retroarch_overlay.presentation.qt.window_drag import QtWindowDragHandle


def test_drag_handle_moves_owning_window_and_releases(qtbot) -> None:
    window = QMainWindow()
    handle = QtWindowDragHandle(window)
    window.setCentralWidget(handle)
    window.setGeometry(100, 120, 400, 500)
    qtbot.addWidget(window)
    window.show()
    frame_origin = window.frameGeometry().topLeft()
    started = []
    handle.drag_started.connect(lambda: started.append(True))

    handle._begin_drag(frame_origin + QPoint(12, 18))
    handle._drag_to(frame_origin + QPoint(62, 88))

    assert window.frameGeometry().topLeft() == frame_origin + QPoint(50, 70)
    assert handle.cursor().shape() == Qt.CursorShape.SizeAllCursor
    assert started == [True]