from __future__ import annotations

from typing import Any

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QMessageBox

from app.ui.review_window import ReviewWindow
from app.ui.review_table_model import ReviewRow


def _review_payload() -> dict[str, Any]:
    return {
        "metadata": {
            "id": 7,
            "source_filename": "ket_qua_boc_tach.json",
            "sha256": "a" * 64,
            "status": "REVIEWING",
            "received_at": "2026-07-27T16:00:00+07:00",
        },
        "document": {
            "v": 1,
            "d": [
                ["DRYU3026167", None, "VTN", "CV", 13_554_000],
                [None, "BL123456789", "CB", "HD", 27_500_000],
            ],
        },
    }


def test_delete_selected_row_requires_confirmation(qtbot, monkeypatch) -> None:
    window = ReviewWindow(_review_payload())
    qtbot.addWidget(window)
    window.show()
    window.table.selectRow(0)
    asked: list[str] = []

    def confirm(*args: Any, **kwargs: Any) -> QMessageBox.StandardButton:
        asked.append(str(args[2]))
        return QMessageBox.StandardButton.Yes

    monkeypatch.setattr(QMessageBox, "question", confirm)

    try:
        window.delete_selected_row()

        assert asked
        assert window.model.rowCount() == 1
        assert window.model.dirty
    finally:
        window.model.mark_clean()
        window.close()


def test_ctrl_s_saves_working_document_and_clears_dirty(qtbot) -> None:
    calls: list[tuple[int, Any]] = []

    def save(batch_id: int, document: Any) -> None:
        calls.append((batch_id, document))

    window = ReviewWindow(_review_payload(), save_handler=save)
    qtbot.addWidget(window)
    window.show()
    window.model.update_row(
        0,
        ReviewRow("DRYU3026167", None, "VTN", "CV", 13_554_001),
    )
    window.activateWindow()
    window.table.setFocus()
    qtbot.wait(20)

    try:
        qtbot.keyClick(
            window.table,
            Qt.Key.Key_S,
            modifier=Qt.KeyboardModifier.ControlModifier,
        )
        qtbot.wait(50)

        assert calls
        assert calls[0][0] == 7
        assert calls[0][1].rows[0].amount == 13_554_001
        assert not window.model.dirty
    finally:
        window.model.mark_clean()
        window.close()


def test_editing_row_updates_status_and_dirty_state(qtbot) -> None:
    window = ReviewWindow(_review_payload())
    qtbot.addWidget(window)

    try:
        window.model.update_row(
            0,
            ReviewRow("DRYU3026167", None, "CB", "CV", 13_554_000),
        )

        assert window.model.dirty
        assert window.model.stats.error == 1
        assert not window.confirm_button.isEnabled()
    finally:
        window.model.mark_clean()
        window.close()
