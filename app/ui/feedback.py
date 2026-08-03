"""Các thành phần phản hồi thị giác dùng chung cho giao diện."""

from __future__ import annotations

from PySide6.QtCore import (
    QAbstractAnimation,
    QEasingCurve,
    QEvent,
    QObject,
    Property,
    QPropertyAnimation,
    QPoint,
    QRectF,
    Qt,
)
from PySide6.QtGui import QColor, QPaintEvent, QPainter, QShowEvent
from PySide6.QtWidgets import (
    QAbstractButton,
    QPushButton,
    QToolButton,
    QWidget,
)


def refresh_widget_style(widget: QObject) -> None:
    """Áp dụng lại QSS sau khi một dynamic property thay đổi."""

    style = getattr(widget, "style", lambda: None)()
    if style is None:
        return
    style.unpolish(widget)
    style.polish(widget)


def set_button_loading(button: QAbstractButton, loading: bool) -> None:
    """Đánh dấu nút đang xử lý để stylesheet hiển thị đúng trạng thái."""

    button.setProperty("loading", loading)
    refresh_widget_style(button)


class LinearLoadingBar(QWidget):
    """Thanh loading mảnh với một đoạn sáng chạy liên tục."""

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("linearLoadingBar")
        self.setFixedHeight(3)
        self._running = False
        self._offset = 0.0
        self._animation = QPropertyAnimation(self, b"progressOffset", self)
        self._animation.setDuration(1050)
        self._animation.setStartValue(0.0)
        self._animation.setEndValue(1.0)
        self._animation.setLoopCount(-1)
        self._animation.setEasingCurve(QEasingCurve.Type.InOutCubic)
        self.setVisible(False)

    def set_running(self, running: bool) -> None:
        self._running = bool(running)
        if self._running:
            self.show()
            if self._animation.state() != QAbstractAnimation.State.Running:
                self._animation.start()
        else:
            self._animation.stop()
            self._offset = 0.0
            self.hide()

    def _get_progress_offset(self) -> float:
        return self._offset

    def _set_progress_offset(self, value: float) -> None:
        self._offset = float(value)
        self.update()

    progressOffset = Property(  # noqa: N815
        float,
        _get_progress_offset,
        _set_progress_offset,
    )

    def showEvent(self, event: QShowEvent) -> None:  # noqa: N802
        super().showEvent(event)
        if (
            self._running
            and self._animation.state() != QAbstractAnimation.State.Running
        ):
            self._animation.start()

    def hideEvent(self, event: QEvent) -> None:  # noqa: N802
        self._animation.stop()
        super().hideEvent(event)

    def paintEvent(self, event: QPaintEvent) -> None:  # noqa: N802
        del event
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        bounds = QRectF(self.rect())
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(QColor("#DCEAFE"))
        painter.drawRoundedRect(bounds, 1.5, 1.5)

        segment_width = max(54.0, bounds.width() * 0.28)
        travel = bounds.width() + segment_width
        x = -segment_width + (travel * self._offset)
        segment = QRectF(x, 0.0, segment_width, bounds.height())
        painter.setBrush(QColor("#2563EB"))
        painter.drawRoundedRect(segment, 1.5, 1.5)


class ButtonPressFeedback(QObject):
    """Tạo chuyển động nhấn nhẹ cho mọi nút mà không đổi logic click."""

    _OFFSET = QPoint(0, 2)

    def __init__(self, parent: QObject | None = None) -> None:
        super().__init__(parent)
        self._origins: dict[QAbstractButton, QPoint] = {}
        self._animations: dict[QAbstractButton, QPropertyAnimation] = {}

    def eventFilter(self, watched: QObject, event: QEvent) -> bool:  # noqa: N802
        if not isinstance(watched, (QPushButton, QToolButton)):
            return False
        if not watched.isEnabled():
            return False

        event_type = event.type()
        keyboard_activation = (
            event_type in (QEvent.Type.KeyPress, QEvent.Type.KeyRelease)
            and getattr(event, "key", lambda: None)()
            in (Qt.Key.Key_Space, Qt.Key.Key_Return, Qt.Key.Key_Enter)
        )
        if event_type == QEvent.Type.MouseButtonPress or (
            event_type == QEvent.Type.KeyPress and keyboard_activation
        ):
            if watched not in self._origins:
                self._origins[watched] = watched.pos()
            self._animate_to(watched, self._origins[watched] + self._OFFSET, 65)
        elif event_type in (
            QEvent.Type.MouseButtonRelease,
            QEvent.Type.Leave,
            QEvent.Type.Hide,
        ) or (event_type == QEvent.Type.KeyRelease and keyboard_activation):
            origin = self._origins.pop(watched, None)
            if origin is not None:
                self._animate_to(watched, origin, 110)
        elif event_type is QEvent.Type.Destroy:
            self._origins.pop(watched, None)
            animation = self._animations.pop(watched, None)
            if animation is not None:
                animation.stop()
        return False

    def _animate_to(
        self, button: QAbstractButton, target: QPoint, duration: int
    ) -> None:
        current = self._animations.get(button)
        if (
            current is not None
            and current.state() == QAbstractAnimation.State.Running
        ):
            current.stop()
        animation = QPropertyAnimation(button, b"pos", self)
        animation.setDuration(duration)
        animation.setStartValue(button.pos())
        animation.setEndValue(target)
        animation.setEasingCurve(QEasingCurve.Type.OutCubic)
        animation.finished.connect(
            lambda target_button=button: self._animations.pop(target_button, None)
        )
        animation.finished.connect(animation.deleteLater)
        self._animations[button] = animation
        animation.start()
