from __future__ import annotations

from app.ui.workflow_page import WorkflowPage


def test_workflow_only_exposes_assistant_action_in_step_one(qtbot) -> None:
    page = WorkflowPage({"assistant_bat_path": ""})
    qtbot.addWidget(page)

    assert page.open_assistant_button.text() == "Mở Trợ lý ảo"
    assert not hasattr(page, "open_inbox_button")
    assert not hasattr(page, "choose_file_button")
    assert page.review_button.isEnabled() is False


def test_valid_batch_shows_saved_message_and_vietnamese_time(qtbot) -> None:
    page = WorkflowPage()
    qtbot.addWidget(page)

    page.set_active_batch(
        {
            "id": 3,
            "source_filename": "ket_qua_boc_tach.json",
            "status": "REVIEWING",
            "last_saved_at": "2026-07-27T22:18:00+07:00",
        }
    )

    assert page.file_status_badge.text() == "Đã có file"
    assert page.file_name_label.text() == "ket_qua_boc_tach.json"
    assert "Đã lưu dữ liệu bóc tách JSON" in page.file_note_label.text()
    assert page.saved_label.text() == (
        "Lưu thành công lần cuối: 22:18 ngày 27/07/2026"
    )
    assert page.review_button.isEnabled()


def test_invalid_batch_never_claims_successful_save(qtbot) -> None:
    page = WorkflowPage()
    qtbot.addWidget(page)

    page.set_active_batch(
        {
            "id": 4,
            "source_filename": "ket_qua_boc_tach.json",
            "status": "INVALID",
            "last_error": "Thiếu khóa d.",
        }
    )

    assert page.file_status_badge.text() == "File không hợp lệ"
    assert page.file_note_label.text() == "Thiếu khóa d."
    assert page.saved_label.text().endswith("—")
    assert not page.review_button.isEnabled()

