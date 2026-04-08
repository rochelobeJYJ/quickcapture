# overlay.py
from PyQt6.QtWidgets import QWidget, QFrame, QHBoxLayout, QPushButton
from PyQt6.QtCore import Qt, QRect, QPoint, pyqtSignal
from PyQt6.QtGui import QPainter, QColor, QPen, QCursor

class OverlayWindow(QWidget):
    capture_requested = pyqtSignal()
    settings_requested = pyqtSignal()
    folder_requested = pyqtSignal()
    ontop_toggled = pyqtSignal(bool)
    exit_requested = pyqtSignal()

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
        self.width_ = settings.get("overlay_width", 600)
        self.height_ = settings.get("overlay_height", 400)
        self.x_ = settings.get("overlay_x", 300)
        self.y_ = settings.get("overlay_y", 200)

        self.setGeometry(self.x_, self.y_ - self.toolbar_h, self.width_, self.height_ + self.toolbar_h)
        self.setMouseTracking(True)
        self.margin = 15

        self.resize_dir = None
        self.is_moving = False
        self.start_pos = QPoint()
        self.start_geometry = QRect()

        self.init_toolbar()

    def init_toolbar(self):
        self.toolbar = QFrame(self)
        self.toolbar.setFixedHeight(30)
        # 테두리 및 회색선 완전히 제거. 오직 깔끔한 흰색 라운딩 배경만 유지
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
        """)
        
        tb_layout = QHBoxLayout(self.toolbar)
        tb_layout.setContentsMargins(4, 2, 4, 2)
        tb_layout.setSpacing(2)
        
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
        
        tb_layout.addWidget(self.btn_ontop)
        tb_layout.addWidget(self.btn_capture)
        tb_layout.addWidget(self.btn_folder)
        tb_layout.addWidget(self.btn_settings)
        tb_layout.addWidget(self.btn_exit)

    def resizeEvent(self, event):
        tb_w = self.toolbar.sizeHint().width()
        t = self.border_thickness
        tb_x = self.width() - tb_w - t
        if tb_x < 0: tb_x = 0
        # 툴바를 경계선 바로 약간 위 (수직 공백 2px) 에 배치하여 완전히 분리된 느낌 
        tb_y = self.toolbar_h - 30 - 2
        if tb_y < 0: tb_y = 0
        self.toolbar.setGeometry(tb_x, tb_y, tb_w, 30)
        super().resizeEvent(event)

    def update_settings(self):
        self.border_color = self.settings.get("border_color", "#ff4d4d")
        self.border_thickness = int(self.settings.get("border_thickness", 4))
        self.update()

    def set_always_on_top(self, value):
        flags = self.windowFlags()
        if value:
            flags |= Qt.WindowType.WindowStaysOnTopHint
        else:
            flags &= ~Qt.WindowType.WindowStaysOnTopHint
        self.setWindowFlags(flags)
        
        # 버튼 체크 상태 동기화
        if hasattr(self, 'btn_ontop') and self.btn_ontop.isChecked() != value:
            self.btn_ontop.blockSignals(True)
            self.btn_ontop.setChecked(value)
            self.btn_ontop.blockSignals(False)
            
        self.show()

    def get_capture_bbox(self):
        ratio = self.devicePixelRatioF()
        rect = self.geometry()
        t = self.border_thickness
        
        c_x = rect.x()
        c_y = rect.y() + self.toolbar_h
        c_w = rect.width()
        c_h = rect.height() - self.toolbar_h
        
        x = int((c_x + t) * ratio)
        y = int((c_y + t) * ratio)
        w = int((c_w - 2 * t) * ratio)
        h = int((c_h - 2 * t) * ratio)
        return (x, y, x + w, y + h)

    def paintEvent(self, event):
        painter = QPainter(self)
        
        c_rect = QRect(0, self.toolbar_h, self.width(), self.height() - self.toolbar_h)
        painter.fillRect(c_rect, QColor(0, 0, 0, 1))

        pen = QPen(QColor(self.border_color))
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
            self.is_moving = getattr(self, "resize_dir", None) is None

    def mouseMoveEvent(self, event):
        pos = event.position().toPoint()
        if not (event.buttons() & Qt.MouseButton.LeftButton):
            rdir = self.get_resize_dir(pos)
            if rdir in ["nw", "se"]: self.setCursor(Qt.CursorShape.SizeFDiagCursor)
            elif rdir in ["ne", "sw"]: self.setCursor(Qt.CursorShape.SizeBDiagCursor)
            elif rdir in ["n", "s"]: self.setCursor(Qt.CursorShape.SizeVerCursor)
            elif rdir in ["w", "e"]: self.setCursor(Qt.CursorShape.SizeHorCursor)
            else: self.setCursor(Qt.CursorShape.SizeAllCursor)

        if event.buttons() & Qt.MouseButton.LeftButton:
            global_pos = event.globalPosition().toPoint()
            dx = global_pos.x() - self.start_pos.x()
            dy = global_pos.y() - self.start_pos.y()

            if self.is_moving:
                new_pos = self.start_geometry.topLeft() + QPoint(dx, dy)
                self.move(new_pos)
            elif self.resize_dir:
                rect = QRect(self.start_geometry)
                if "w" in self.resize_dir: rect.setLeft(rect.left() + dx)
                if "e" in self.resize_dir: rect.setRight(rect.right() + dx)
                if "n" in self.resize_dir: rect.setTop(rect.top() + dy)
                if "s" in self.resize_dir: rect.setBottom(rect.bottom() + dy)
                
                if rect.width() < 100:
                    if "w" in self.resize_dir: rect.setLeft(rect.right() - 100)
                    else: rect.setRight(rect.left() + 100)
                if rect.height() - self.toolbar_h < 100:
                    if "n" in self.resize_dir: rect.setTop(rect.bottom() - self.toolbar_h - 100)
                    else: rect.setBottom(rect.top() + self.toolbar_h + 100)
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