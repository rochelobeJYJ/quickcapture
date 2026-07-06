# overlay.py
import math
from PyQt6.QtWidgets import QWidget, QFrame, QHBoxLayout, QPushButton, QLabel
from PyQt6.QtCore import Qt, QRect, QPoint, pyqtSignal, QTimer
from PyQt6.QtGui import QPainter, QColor, QPen


class OverlayWindow(QWidget):
    capture_requested = pyqtSignal()
    settings_requested = pyqtSignal()
    folder_requested = pyqtSignal()
    ontop_toggled = pyqtSignal(bool)
    exit_requested = pyqtSignal()

    MIN_CAPTURE_SIZE = 100  # 캡처 영역 최소 크기 (논리 px)

    def __init__(self, settings):
        super().__init__()
        self.settings = settings
        self.setWindowFlags(
            Qt.WindowType.FramelessWindowHint |
            Qt.WindowType.WindowStaysOnTopHint |
            Qt.WindowType.Tool
        )
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)

        self.border_color = settings.get("border_color", "#ff4d4d")
        self.border_thickness = int(settings.get("border_thickness", 4))

        self.toolbar_h = 36
        x = settings.get("overlay_x", 300)
        y = settings.get("overlay_y", 200)
        w = settings.get("overlay_width", 600)
        h = settings.get("overlay_height", 400)
        self.setGeometry(x, y - self.toolbar_h, w, h + self.toolbar_h)

        self.setMouseTracking(True)
        self.margin = 15

        self.resize_dir = None
        self.is_moving = False
        self.start_pos = QPoint()
        self.start_geometry = QRect()

        # 캡처 성공 플래시 — 원래 색을 건드리지 않고 상태 플래그로만 처리
        self._flashing = False
        self._flash_timer = QTimer(self)
        self._flash_timer.setSingleShot(True)
        self._flash_timer.timeout.connect(self._end_flash)

        self.init_toolbar()

    def init_toolbar(self):
        self.toolbar = QFrame(self)
        self.toolbar.setFixedHeight(30)
        self.toolbar.setStyleSheet("""
            QFrame {
                background-color: rgba(255, 255, 255, 245);
                border-radius: 6px;
            }
            QPushButton {
                background: transparent;
                border: none;
                font-size: 15px;
                padding: 3px 5px;
            }
            QPushButton:hover {
                background-color: #f3f4f6;
                border-radius: 4px;
            }
            QPushButton:pressed {
                background-color: #e5e7eb;
            }
            QPushButton:checked {
                background-color: #3b82f6;
                color: #ffffff;
                border-radius: 4px;
            }
            QLabel {
                color: #6b7280;
                font-size: 11px;
                font-weight: bold;
                font-family: 'Consolas', monospace;
                padding: 0px 6px;
            }
        """)

        tb_layout = QHBoxLayout(self.toolbar)
        tb_layout.setContentsMargins(4, 2, 4, 2)
        tb_layout.setSpacing(2)

        # 캡처될 실제(물리) 픽셀 크기 표시
        self.size_label = QLabel("")
        self.size_label.setToolTip("캡처 영역 크기 (실제 픽셀)")

        self.btn_ontop = QPushButton("📌")
        self.btn_ontop.setToolTip("항상 위에 표시")
        self.btn_ontop.setCheckable(True)
        self.btn_ontop.setChecked(self.settings.get("always_on_top", True))
        self.btn_ontop.clicked.connect(self.ontop_toggled.emit)

        self.btn_capture = QPushButton("📸")
        self.btn_capture.setToolTip("즉시 캡처")
        self.btn_capture.clicked.connect(self.capture_requested.emit)

        self.btn_folder = QPushButton("📂")
        self.btn_folder.setToolTip("저장 폴더 열기")
        self.btn_folder.clicked.connect(self.folder_requested.emit)

        self.btn_settings = QPushButton("⚙️")
        self.btn_settings.setToolTip("메인 설정 창 열기")
        self.btn_settings.clicked.connect(self.settings_requested.emit)

        self.btn_exit = QPushButton("✖️")
        self.btn_exit.setToolTip("프로그램 종료")
        self.btn_exit.clicked.connect(self.exit_requested.emit)

        tb_layout.addWidget(self.size_label)
        tb_layout.addWidget(self.btn_ontop)
        tb_layout.addWidget(self.btn_capture)
        tb_layout.addWidget(self.btn_folder)
        tb_layout.addWidget(self.btn_settings)
        tb_layout.addWidget(self.btn_exit)

    def set_hotkey_hint(self, hotkey):
        self.btn_capture.setToolTip(f"즉시 캡처 ({hotkey.upper()})  ·  영역 더블클릭으로도 가능")

    def _refresh_size_label(self):
        bbox = self.get_capture_bbox()
        self.size_label.setText(f"{bbox[2] - bbox[0]}×{bbox[3] - bbox[1]}")

    def resizeEvent(self, event):
        self._refresh_size_label()
        tb_w = self.toolbar.sizeHint().width()
        t = self.border_thickness
        tb_x = max(0, self.width() - tb_w - t)
        # 툴바를 캡처 경계선 바로 위(수직 공백 2px)에 배치
        tb_y = max(0, self.toolbar_h - 30 - 2)
        self.toolbar.setGeometry(tb_x, tb_y, tb_w, 30)
        super().resizeEvent(event)

    def update_settings(self):
        self.border_color = self.settings.get("border_color", "#ff4d4d")
        self.border_thickness = int(self.settings.get("border_thickness", 4))
        self._refresh_size_label()
        self.update()

    def set_always_on_top(self, value):
        was_visible = self.isVisible()
        flags = self.windowFlags()
        if value:
            flags |= Qt.WindowType.WindowStaysOnTopHint
        else:
            flags &= ~Qt.WindowType.WindowStaysOnTopHint
        self.setWindowFlags(flags)

        # 툴바 버튼 체크 상태 동기화
        if self.btn_ontop.isChecked() != value:
            self.btn_ontop.blockSignals(True)
            self.btn_ontop.setChecked(value)
            self.btn_ontop.blockSignals(False)

        if was_visible:
            self.show()

    def flash(self, duration_ms=120):
        """캡처 성공 시 테두리를 잠깐 흰색으로 점멸."""
        self._flashing = True
        self.update()
        self._flash_timer.start(duration_ms)

    def _end_flash(self):
        self._flashing = False
        self.update()

    def get_capture_bbox(self):
        ratio = self.devicePixelRatioF()
        rect = self.geometry()
        t = self.border_thickness
        # QPen은 선 너비의 절반을 안쪽으로 그리므로 ceil(t/2) + 1px 여유를 줘서 테두리가 캡처에 포함되지 않도록 함
        inset = math.ceil(t / 2) + 1

        c_x = rect.x()
        c_y = rect.y() + self.toolbar_h
        c_w = rect.width()
        c_h = rect.height() - self.toolbar_h

        x = int((c_x + inset) * ratio)
        y = int((c_y + inset) * ratio)
        w = int((c_w - 2 * inset) * ratio)
        h = int((c_h - 2 * inset) * ratio)
        return (x, y, x + w, y + h)

    def paintEvent(self, event):
        painter = QPainter(self)

        c_rect = QRect(0, self.toolbar_h, self.width(), self.height() - self.toolbar_h)
        # 완전 투명이면 마우스 이벤트가 통과하므로 알파 1의 사실상 투명한 채움 유지
        painter.fillRect(c_rect, QColor(0, 0, 0, 1))

        color = "#ffffff" if self._flashing else self.border_color
        pen = QPen(QColor(color))
        pen.setWidth(self.border_thickness)

        t2 = self.border_thickness / 2.0
        painter.setPen(pen)
        painter.drawRect(int(c_rect.x() + t2), int(c_rect.y() + t2),
                         int(c_rect.width() - self.border_thickness),
                         int(c_rect.height() - self.border_thickness))

    def get_resize_dir(self, pos):
        x, y = pos.x(), pos.y()
        if y < self.toolbar_h:
            return None

        cy = y - self.toolbar_h
        w, ch = self.width(), self.height() - self.toolbar_h
        m = self.margin
        res = ""
        if cy < m: res += "n"
        elif cy > ch - m: res += "s"
        if x < m: res += "w"
        elif x > w - m: res += "e"
        return res if res else None

    def mousePressEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton:
            pos = event.position().toPoint()
            if pos.y() < self.toolbar_h:
                self.is_moving = False
                return

            self.start_pos = event.globalPosition().toPoint()
            self.start_geometry = self.geometry()
            self.resize_dir = self.get_resize_dir(pos)
            self.is_moving = self.resize_dir is None

    def mouseMoveEvent(self, event):
        pos = event.position().toPoint()
        if not (event.buttons() & Qt.MouseButton.LeftButton):
            if pos.y() < self.toolbar_h:
                self.setCursor(Qt.CursorShape.ArrowCursor)
            else:
                rdir = self.get_resize_dir(pos)
                if rdir in ("nw", "se"): self.setCursor(Qt.CursorShape.SizeFDiagCursor)
                elif rdir in ("ne", "sw"): self.setCursor(Qt.CursorShape.SizeBDiagCursor)
                elif rdir in ("n", "s"): self.setCursor(Qt.CursorShape.SizeVerCursor)
                elif rdir in ("w", "e"): self.setCursor(Qt.CursorShape.SizeHorCursor)
                else: self.setCursor(Qt.CursorShape.SizeAllCursor)

        if event.buttons() & Qt.MouseButton.LeftButton:
            global_pos = event.globalPosition().toPoint()
            dx = global_pos.x() - self.start_pos.x()
            dy = global_pos.y() - self.start_pos.y()

            if self.is_moving:
                self.move(self.start_geometry.topLeft() + QPoint(dx, dy))
            elif self.resize_dir:
                rect = QRect(self.start_geometry)
                if "w" in self.resize_dir: rect.setLeft(rect.left() + dx)
                if "e" in self.resize_dir: rect.setRight(rect.right() + dx)
                if "n" in self.resize_dir: rect.setTop(rect.top() + dy)
                if "s" in self.resize_dir: rect.setBottom(rect.bottom() + dy)

                min_w = self.MIN_CAPTURE_SIZE
                min_h = self.MIN_CAPTURE_SIZE + self.toolbar_h
                if rect.width() < min_w:
                    if "w" in self.resize_dir: rect.setLeft(rect.right() - min_w)
                    else: rect.setRight(rect.left() + min_w)
                if rect.height() < min_h:
                    if "n" in self.resize_dir: rect.setTop(rect.bottom() - min_h)
                    else: rect.setBottom(rect.top() + min_h)
                self.setGeometry(rect)

    def mouseReleaseEvent(self, event):
        self.is_moving = False
        self.resize_dir = None
        self.save_geometry()

    def mouseDoubleClickEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton and event.position().toPoint().y() >= self.toolbar_h:
            self.capture_requested.emit()

    def save_geometry(self):
        g = self.geometry()
        self.settings["overlay_x"] = g.x()
        self.settings["overlay_y"] = g.y() + self.toolbar_h
        self.settings["overlay_width"] = g.width()
        self.settings["overlay_height"] = g.height() - self.toolbar_h
