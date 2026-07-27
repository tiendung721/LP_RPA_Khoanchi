"""Bảng màu và stylesheet dùng chung cho giao diện sáng trên Windows."""

from __future__ import annotations

from PySide6.QtGui import QColor, QPalette
from PySide6.QtWidgets import QApplication

PRIMARY = "#2563EB"
PRIMARY_DARK = "#1D4ED8"
PRIMARY_LIGHT = "#EFF6FF"
TEXT = "#172033"
MUTED_TEXT = "#64748B"
BORDER = "#D8E0EA"
SURFACE = "#FFFFFF"
SURFACE_ALT = "#F7F9FC"
SUCCESS = "#15803D"
SUCCESS_BG = "#ECFDF3"
WARNING = "#A16207"
WARNING_BG = "#FFF8DB"
ERROR = "#B42318"
ERROR_BG = "#FFF0F0"


APP_STYLESHEET = f"""
QWidget {{
    color: {TEXT};
    font-family: "Segoe UI";
    font-size: 10pt;
}}
QMainWindow, QDialog, QWidget#applicationRoot {{
    background: {SURFACE_ALT};
}}
QLabel#pageTitle {{
    font-size: 20pt;
    font-weight: 700;
    color: #111827;
}}
QLabel#pageSubtitle, QLabel[muted="true"] {{
    color: {MUTED_TEXT};
}}
QLabel[status="error"] {{
    color: {ERROR};
}}
QLabel[status="warning"] {{
    color: {WARNING};
}}
QLabel[status="success"] {{
    color: {SUCCESS};
}}
QFrame[card="true"], QGroupBox {{
    background: {SURFACE};
    border: 1px solid {BORDER};
    border-radius: 9px;
}}
QFrame[card="true"] {{
    padding: 1px;
}}
QFrame[upcoming="true"] {{
    background: #F1F5F9;
    border: 1px dashed #B9C4D2;
    border-radius: 9px;
}}
QGroupBox {{
    margin-top: 14px;
    padding: 16px 12px 12px 12px;
    font-weight: 600;
}}
QGroupBox::title {{
    subcontrol-origin: margin;
    left: 12px;
    padding: 0 5px;
    color: #334155;
}}
QPushButton, QToolButton {{
    min-height: 30px;
    padding: 2px 13px;
    border: 1px solid #C6D0DD;
    border-radius: 6px;
    background: {SURFACE};
}}
QPushButton:hover, QToolButton:hover {{
    border-color: #8FA0B5;
    background: #F8FAFC;
}}
QPushButton:pressed, QToolButton:pressed {{
    background: #EEF2F7;
}}
QPushButton:disabled, QToolButton:disabled {{
    color: #98A2B3;
    background: #F2F4F7;
    border-color: #E4E7EC;
}}
QPushButton[primary="true"] {{
    color: white;
    background: {PRIMARY};
    border-color: {PRIMARY};
    font-weight: 600;
}}
QPushButton[primary="true"]:hover {{
    background: {PRIMARY_DARK};
    border-color: {PRIMARY_DARK};
}}
QPushButton[danger="true"] {{
    color: {ERROR};
    border-color: #F3B3AE;
}}
QLineEdit, QComboBox, QSpinBox, QDoubleSpinBox, QPlainTextEdit {{
    min-height: 30px;
    padding: 1px 7px;
    border: 1px solid #C6D0DD;
    border-radius: 6px;
    background: {SURFACE};
    selection-background-color: #BFDBFE;
}}
QPlainTextEdit {{
    padding: 8px;
}}
QLineEdit:focus, QComboBox:focus, QSpinBox:focus,
QDoubleSpinBox:focus, QPlainTextEdit:focus {{
    border: 1px solid {PRIMARY};
}}
QLineEdit[invalid="true"], QComboBox[invalid="true"] {{
    border: 1px solid {ERROR};
    background: {ERROR_BG};
}}
QComboBox::drop-down {{
    border: 0;
    width: 24px;
}}
QTableView {{
    background: {SURFACE};
    alternate-background-color: #F8FAFC;
    border: 1px solid {BORDER};
    border-radius: 7px;
    gridline-color: #E8EDF3;
    selection-background-color: #DBEAFE;
    selection-color: {TEXT};
}}
QTableView::item {{
    padding: 5px;
}}
QHeaderView::section {{
    background: #EDF2F7;
    color: #334155;
    padding: 7px 5px;
    border: 0;
    border-right: 1px solid #D7DFE9;
    border-bottom: 1px solid #D7DFE9;
    font-weight: 600;
}}
QListWidget#navigation {{
    border: 0;
    background: #12233F;
    color: #DCE6F5;
    outline: 0;
    padding: 10px 7px;
}}
QListWidget#navigation::item {{
    min-height: 38px;
    border-radius: 7px;
    padding: 3px 10px;
    margin: 2px 0;
}}
QListWidget#navigation::item:hover {{
    background: #203A60;
}}
QListWidget#navigation::item:selected {{
    background: {PRIMARY};
    color: white;
    font-weight: 600;
}}
QStatusBar {{
    background: {SURFACE};
    border-top: 1px solid {BORDER};
}}
QScrollBar:vertical {{
    width: 11px;
    background: transparent;
}}
QScrollBar::handle:vertical {{
    min-height: 24px;
    border-radius: 5px;
    background: #C5CFDB;
}}
QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical {{
    height: 0;
}}
"""


def apply_application_theme(application: QApplication) -> None:
    """Áp dụng font, palette và stylesheet nhất quán cho toàn ứng dụng."""

    application.setStyle("Fusion")
    palette = QPalette()
    palette.setColor(QPalette.ColorRole.Window, QColor(SURFACE_ALT))
    palette.setColor(QPalette.ColorRole.WindowText, QColor(TEXT))
    palette.setColor(QPalette.ColorRole.Base, QColor(SURFACE))
    palette.setColor(QPalette.ColorRole.AlternateBase, QColor(SURFACE_ALT))
    palette.setColor(QPalette.ColorRole.Text, QColor(TEXT))
    palette.setColor(QPalette.ColorRole.Button, QColor(SURFACE))
    palette.setColor(QPalette.ColorRole.ButtonText, QColor(TEXT))
    palette.setColor(QPalette.ColorRole.Highlight, QColor(PRIMARY))
    palette.setColor(QPalette.ColorRole.HighlightedText, QColor("#FFFFFF"))
    palette.setColor(QPalette.ColorGroup.Disabled, QPalette.ColorRole.Text, QColor("#98A2B3"))
    application.setPalette(palette)
    application.setStyleSheet(APP_STYLESHEET)


# Tên ngắn thuận tiện cho mã khởi động và tương thích với các bản tích hợp cũ.
apply_theme = apply_application_theme

