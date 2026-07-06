# main.py
import sys
import os
import re
import json
import threading
import time
from datetime import datetime

import ctypes
try:
    ctypes.windll.shcore.SetProcessDpiAwareness(1)
except (AttributeError, OSError):
    try:
        ctypes.windll.user32.SetProcessDPIAware()
    except (AttributeError, OSError):
        pass

from PyQt6.QtWidgets import (QApplication, QMainWindow, QWidget, QVBoxLayout,
                             QHBoxLayout, QLabel, QLineEdit, QPushButton,
                             QComboBox, QCheckBox, QFileDialog, QColorDialog,
                             QGridLayout, QFrame, QDialog, QSpinBox,
                             QSystemTrayIcon, QMenu)
from PyQt6.QtCore import Qt, pyqtSignal, QObject
from PyQt6.QtGui import QColor, QKeySequence, QIcon

import keyboard
import mss
from PIL import Image

from overlay import OverlayWindow


def app_dir():
    """실행 형태(스크립트/exe)와 무관하게 항상 같은 위치를 반환."""
    if getattr(sys, "frozen", False):
        return os.path.dirname(sys.executable)
    return os.path.dirname(os.path.abspath(__file__))


def resource_path(name):
    """PyInstaller 번들 내부 리소스 경로."""
    base = getattr(sys, "_MEIPASS", os.path.dirname(os.path.abspath(__file__)))
    return os.path.join(base, name)


SETTINGS_FILE = os.path.join(app_dir(), "settings.json")

DEFAULT_SETTINGS = {
    "save_folder": os.path.join(os.path.expanduser("~"), "Pictures", "QuickCapture"),
    "hotkey": "ctrl+shift+c",
    "border_color": "#ff4d4d",
    "border_thickness": 4,
    "overlay_x": 300,
    "overlay_y": 200,
    "overlay_width": 600,
    "overlay_height": 400,
    "always_on_top": True,
    "save_format": "PNG",
    "jpg_quality": 95,
    "custom_prefix": "capture",
    "template": "numbered",
}

# 구버전 settings.json 의 template 값 → 새 키 매핑
LEGACY_TEMPLATES = {
    "image_{:03d}_HHMMSS.png": "numbered",
    "capture_{YYMMDD_HHMMSS}.png": "datetime",
    "{custom}_{:04d}.png": "custom",
}

TEMPLATE_OPTIONS = [
    ("numbered", "image_001_시분초 (연번 + 시간)"),
    ("datetime", "capture_날짜_시간"),
    ("custom", "직접 지정한 이름_0001"),
]

FONT_FAMILY = "'Pretendard', 'Malgun Gothic', sans-serif"


class Signals(QObject):
    hotkey_pressed = pyqtSignal()
    capture_done = pyqtSignal(int, str)   # (세션 카운트, 저장 파일명)
    capture_failed = pyqtSignal(str)
    overlay_hide = pyqtSignal()
    overlay_show = pyqtSignal()


class HotkeyDialog(QDialog):
    def __init__(self, current_hotkey, parent=None):
        super().__init__(parent)
        self.setWindowTitle("단축키 변경")
        self.setFixedSize(320, 150)
        self.hotkey = None
        self.setStyleSheet(f"""
            QDialog {{ background-color: #f7f8fa; }}
            QLabel {{ color: #333333; font-family: {FONT_FAMILY}; font-size: 13px; }}
        """)
        layout = QVBoxLayout(self)

        lbl = QLabel(
            f"현재 단축키: <b style='color:#0078d4'>{current_hotkey.upper()}</b><br><br>"
            "사용할 새로운 단축키를 직접 누르세요.<br>(취소하려면 ESC)"
        )
        lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(lbl)
        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)

    def keyPressEvent(self, event):
        key = event.key()
        modifiers = []

        if event.modifiers() & Qt.KeyboardModifier.ControlModifier: modifiers.append("ctrl")
        if event.modifiers() & Qt.KeyboardModifier.AltModifier: modifiers.append("alt")
        if event.modifiers() & Qt.KeyboardModifier.ShiftModifier: modifiers.append("shift")

        if key in (Qt.Key.Key_Control, Qt.Key.Key_Shift, Qt.Key.Key_Alt, Qt.Key.Key_Meta):
            return

        if key == Qt.Key.Key_Escape and not modifiers:
            self.reject()
            return

        key_name = QKeySequence(key).toString().lower()
        if key_name == "return": key_name = "enter"

        if key_name:
            self.hotkey = "+".join(modifiers + [key_name])
            self.accept()


class CaptureApp(QMainWindow):
    MIN_CAPTURE_INTERVAL = 0.2  # 초 — 연타 방지

    def __init__(self):
        super().__init__()
        self.settings = self.load_settings()
        self.last_capture_time = 0.0
        self.session_count = 0
        self._count_lock = threading.Lock()

        self.signals = Signals()
        # 키보드 훅 스레드 → 시그널을 통해 메인(GUI) 스레드에서 캡처 시작
        self.signals.hotkey_pressed.connect(self.trigger_capture)
        self.signals.capture_done.connect(self.on_capture_done)
        self.signals.capture_failed.connect(self.on_capture_failed)

        self.init_ui()

        self.overlay = OverlayWindow(self.settings)
        self.overlay.capture_requested.connect(self.trigger_capture)
        self.overlay.folder_requested.connect(self.open_saved_folder)
        self.overlay.settings_requested.connect(self.show_to_front)
        self.overlay.ontop_toggled.connect(self.ontop_cb.setChecked)
        self.overlay.exit_requested.connect(self.quit_app)
        self.signals.overlay_hide.connect(self.overlay.hide)
        self.signals.overlay_show.connect(self.overlay.show)
        self.overlay.set_hotkey_hint(self.settings["hotkey"])
        self.overlay.show()

        self.init_tray()
        self.register_hotkey()

    # ------------------------------------------------------------------ 설정

    def load_settings(self):
        settings = dict(DEFAULT_SETTINGS)
        try:
            with open(SETTINGS_FILE, "r", encoding="utf-8") as f:
                loaded = json.load(f)
            if isinstance(loaded, dict):
                settings.update(loaded)
        except (OSError, json.JSONDecodeError, ValueError):
            pass

        settings["template"] = LEGACY_TEMPLATES.get(settings["template"], settings["template"])
        if settings["template"] not in ("numbered", "datetime", "custom"):
            settings["template"] = "numbered"
        return settings

    def save_settings(self):
        try:
            with open(SETTINGS_FILE, "w", encoding="utf-8") as f:
                json.dump(self.settings, f, ensure_ascii=False, indent=2)
        except OSError:
            self.set_status("설정 파일 저장 실패", error=True)

    # ------------------------------------------------------------------ UI

    def init_ui(self):
        self.setWindowTitle("QuickCapture Pro")
        self.setWindowIcon(QIcon(resource_path("icon.ico")))
        # 설정창이 오버레이(크롭 영역)보다 항상 위에 표시되도록 함
        self.setWindowFlags(self.windowFlags() | Qt.WindowType.WindowStaysOnTopHint)

        self.setStyleSheet(f"""
            QMainWindow {{ background-color: #f0f2f5; }}
            QLabel {{ color: #374151; font-family: {FONT_FAMILY}; font-size: 13px; }}
            QLabel#section {{ color: #6b7280; font-size: 11px; font-weight: bold; letter-spacing: 1px; }}
            QLabel#field {{ font-weight: bold; }}
            QLineEdit, QComboBox, QSpinBox {{
                background-color: #ffffff; color: #333333;
                border: 1px solid #d1d5db; border-radius: 5px;
                padding: 5px 10px; font-size: 12px; font-family: {FONT_FAMILY};
            }}
            QLineEdit:focus, QComboBox:focus, QSpinBox:focus {{ border: 1px solid #0078d4; }}
            QLineEdit:read-only {{ background-color: #f9fafb; color: #6b7280; }}
            QPushButton {{
                background-color: #0078d4; color: #ffffff;
                border: none; border-radius: 5px;
                padding: 6px 14px; font-weight: bold; font-size: 12px; font-family: {FONT_FAMILY};
            }}
            QPushButton:hover {{ background-color: #106ebe; }}
            QPushButton:pressed {{ background-color: #005a9e; }}
            QPushButton#light_btn {{ background-color: #e5e7eb; color: #374151; }}
            QPushButton#light_btn:hover {{ background-color: #d1d5db; }}
            QCheckBox {{ color: #374151; font-size: 13px; font-weight: bold; font-family: {FONT_FAMILY}; }}
            QFrame#card {{ background-color: #ffffff; border-radius: 8px; border: 1px solid #e5e7eb; }}
            QComboBox::drop-down {{ border: 0px; width: 20px; }}
            QComboBox QAbstractItemView {{
                background-color: #ffffff; color: #333333;
                selection-background-color: #e0efff; selection-color: #111827;
            }}
        """)

        central_widget = QWidget()
        self.setCentralWidget(central_widget)
        main_layout = QVBoxLayout(central_widget)
        main_layout.setContentsMargins(16, 14, 16, 12)
        main_layout.setSpacing(10)

        title_label = QLabel("QUICK CAPTURE")
        title_label.setStyleSheet(
            f"font-size: 20px; font-weight: 900; color: #1f2937; letter-spacing: 1px; font-family: {FONT_FAMILY};"
        )
        main_layout.addWidget(title_label, alignment=Qt.AlignmentFlag.AlignCenter)

        # ---- 저장 설정 카드 ----
        save_card = QFrame()
        save_card.setObjectName("card")
        save_grid = QGridLayout(save_card)
        save_grid.setContentsMargins(18, 14, 18, 16)
        save_grid.setVerticalSpacing(12)
        save_grid.setHorizontalSpacing(12)

        section1 = QLabel("저장 설정")
        section1.setObjectName("section")
        save_grid.addWidget(section1, 0, 0, 1, 3)

        save_grid.addWidget(self._field_label("저장 폴더"), 1, 0)
        self.folder_input = QLineEdit(self.settings["save_folder"])
        self.folder_input.setReadOnly(True)
        self.folder_input.setToolTip(self.settings["save_folder"])
        save_grid.addWidget(self.folder_input, 1, 1)
        folder_btn = QPushButton("변경")
        folder_btn.setObjectName("light_btn")
        folder_btn.clicked.connect(self.change_folder)
        save_grid.addWidget(folder_btn, 1, 2)

        save_grid.addWidget(self._field_label("저장 포맷"), 2, 0)
        self.format_combo = QComboBox()
        self.format_combo.addItems(["PNG", "JPG"])
        self.format_combo.setCurrentText(self.settings["save_format"])
        self.format_combo.currentTextChanged.connect(self.update_format)
        save_grid.addWidget(self.format_combo, 2, 1, 1, 2)

        save_grid.addWidget(self._field_label("파일명 양식"), 3, 0)
        self.template_combo = QComboBox()
        for key, label in TEMPLATE_OPTIONS:
            self.template_combo.addItem(label, key)
        idx = self.template_combo.findData(self.settings["template"])
        self.template_combo.setCurrentIndex(max(0, idx))
        self.template_combo.currentIndexChanged.connect(self.update_template)
        save_grid.addWidget(self.template_combo, 3, 1, 1, 2)

        save_grid.addWidget(self._field_label("직접 지정 이름"), 4, 0)
        self.prefix_input = QLineEdit(self.settings["custom_prefix"])
        self.prefix_input.setPlaceholderText("'직접 지정한 이름' 양식에서 사용됩니다")
        self.prefix_input.textChanged.connect(self.update_prefix)
        self.prefix_input.editingFinished.connect(self.save_settings)
        save_grid.addWidget(self.prefix_input, 4, 1, 1, 2)

        main_layout.addWidget(save_card)

        # ---- 캡처/오버레이 설정 카드 ----
        cap_card = QFrame()
        cap_card.setObjectName("card")
        cap_grid = QGridLayout(cap_card)
        cap_grid.setContentsMargins(18, 14, 18, 16)
        cap_grid.setVerticalSpacing(12)
        cap_grid.setHorizontalSpacing(12)

        section2 = QLabel("캡처 · 오버레이")
        section2.setObjectName("section")
        cap_grid.addWidget(section2, 0, 0, 1, 4)

        cap_grid.addWidget(self._field_label("단축키"), 1, 0)
        self.hotkey_btn = QPushButton(self.settings["hotkey"].upper())
        self.hotkey_btn.setToolTip("클릭 후 새 단축키를 누르세요")
        self.hotkey_btn.clicked.connect(self.change_hotkey)
        cap_grid.addWidget(self.hotkey_btn, 1, 1, 1, 3)

        cap_grid.addWidget(self._field_label("테두리"), 2, 0)
        self.color_btn = QPushButton()
        self.color_btn.setFixedSize(40, 26)
        self.color_btn.setToolTip("오버레이 테두리 색 변경")
        self.color_btn.clicked.connect(self.change_border)
        self._refresh_color_button()
        cap_grid.addWidget(self.color_btn, 2, 1)

        self.thickness_spin = QSpinBox()
        self.thickness_spin.setRange(1, 12)
        self.thickness_spin.setValue(int(self.settings["border_thickness"]))
        self.thickness_spin.setSuffix(" px")
        self.thickness_spin.setToolTip("오버레이 테두리 두께")
        self.thickness_spin.valueChanged.connect(self.update_thickness)
        cap_grid.addWidget(self.thickness_spin, 2, 2)
        cap_grid.setColumnStretch(3, 1)

        self.ontop_cb = QCheckBox("오버레이 창을 항상 맨 위에 표시")
        self.ontop_cb.setChecked(bool(self.settings["always_on_top"]))
        self.ontop_cb.stateChanged.connect(self.toggle_ontop)
        cap_grid.addWidget(self.ontop_cb, 3, 0, 1, 4)

        main_layout.addWidget(cap_card)

        # ---- 세션 정보 ----
        stat_card = QFrame()
        stat_card.setObjectName("card")
        stat_layout = QHBoxLayout(stat_card)
        stat_layout.setContentsMargins(14, 8, 10, 8)

        self.count_label = QLabel(f"현재 세션 캡처: {self.session_count}장")
        self.count_label.setStyleSheet("color: #0078d4; font-weight: bold;")
        stat_layout.addWidget(self.count_label, stretch=1)

        reset_btn = QPushButton("초기화")
        reset_btn.setObjectName("light_btn")
        reset_btn.setToolTip("세션 캡처 횟수를 0으로 초기화")
        reset_btn.clicked.connect(self.reset_session)
        stat_layout.addWidget(reset_btn)

        open_folder_btn = QPushButton("저장 폴더 열기")
        open_folder_btn.setObjectName("light_btn")
        open_folder_btn.clicked.connect(self.open_saved_folder)
        stat_layout.addWidget(open_folder_btn)

        main_layout.addWidget(stat_card)

        # ---- 상태 표시줄 ----
        self.status_label = QLabel("준비됨 — 오버레이 영역을 조절하고 단축키로 캡처하세요")
        self.status_label.setStyleSheet("color: #6b7280; font-size: 11px;")
        main_layout.addWidget(self.status_label)

        self.setFixedWidth(470)

    @staticmethod
    def _field_label(text):
        lbl = QLabel(text)
        lbl.setObjectName("field")
        return lbl

    def _refresh_color_button(self):
        color = self.settings["border_color"]
        self.color_btn.setStyleSheet(
            f"QPushButton {{ background-color: {color}; border: 1px solid #d1d5db; border-radius: 5px; }}"
            f"QPushButton:hover {{ border: 2px solid #0078d4; }}"
        )

    def set_status(self, text, error=False):
        color = "#dc2626" if error else "#6b7280"
        self.status_label.setStyleSheet(f"color: {color}; font-size: 11px;")
        self.status_label.setText(text)

    # ------------------------------------------------------------------ 트레이

    def init_tray(self):
        self.tray = QSystemTrayIcon(QIcon(resource_path("icon.ico")), self)
        self.tray.setToolTip("QuickCapture Pro")

        menu = QMenu()
        menu.addAction("즉시 캡처", self.trigger_capture)
        menu.addAction("오버레이 보이기/숨기기", self.toggle_overlay)
        menu.addAction("설정 열기", self.show_to_front)
        menu.addSeparator()
        menu.addAction("종료", self.quit_app)
        self._tray_menu = menu
        self.tray.setContextMenu(menu)
        self.tray.activated.connect(self._on_tray_activated)
        self.tray.show()

    def _on_tray_activated(self, reason):
        if reason == QSystemTrayIcon.ActivationReason.DoubleClick:
            self.show_to_front()

    def toggle_overlay(self):
        if self.overlay.isVisible():
            self.overlay.hide()
        else:
            self.overlay.show()

    # ------------------------------------------------------------------ 설정 변경 핸들러

    def change_folder(self):
        folder = QFileDialog.getExistingDirectory(self, "저장 폴더 선택", self.settings["save_folder"])
        if folder:
            self.settings["save_folder"] = folder
            self.folder_input.setText(folder)
            self.folder_input.setToolTip(folder)
            os.makedirs(folder, exist_ok=True)
            self.save_settings()

    def open_saved_folder(self):
        folder = self.settings["save_folder"]
        try:
            os.makedirs(folder, exist_ok=True)
            os.startfile(folder)
        except OSError:
            self.set_status(f"폴더를 열 수 없습니다: {folder}", error=True)

    def change_hotkey(self):
        keyboard.unhook_all()
        dialog = HotkeyDialog(self.settings["hotkey"], self)
        if dialog.exec() == QDialog.DialogCode.Accepted and dialog.hotkey:
            self.settings["hotkey"] = dialog.hotkey
            self.hotkey_btn.setText(dialog.hotkey.upper())
            self.overlay.set_hotkey_hint(dialog.hotkey)
            self.save_settings()
        self.register_hotkey()

    def register_hotkey(self):
        try:
            keyboard.remove_all_hotkeys()
        except (AttributeError, KeyError, ValueError):
            pass
        hk = self.settings["hotkey"]
        try:
            # 훅 스레드에서는 시그널만 발생시키고, 실제 캡처는 메인 스레드에서 수행
            keyboard.add_hotkey(hk, self.signals.hotkey_pressed.emit, suppress=True)
            self.set_status(f"준비됨 — {hk.upper()} 로 캡처")
        except (ValueError, OSError):
            self.set_status(f"단축키 '{hk.upper()}' 등록 실패 — 다른 키를 지정하세요", error=True)

    def update_format(self, text):
        self.settings["save_format"] = text
        self.save_settings()

    def update_template(self, index):
        self.settings["template"] = self.template_combo.itemData(index)
        self.save_settings()

    def update_prefix(self, text):
        # 파일 저장은 editingFinished 에서 — 키 입력마다 디스크 쓰기 방지
        self.settings["custom_prefix"] = text

    def update_thickness(self, value):
        self.settings["border_thickness"] = value
        self.overlay.update_settings()
        self.save_settings()

    def toggle_ontop(self, state):
        val = Qt.CheckState(state) == Qt.CheckState.Checked
        self.settings["always_on_top"] = val
        self.overlay.set_always_on_top(val)
        self.save_settings()

    def change_border(self):
        color = QColorDialog.getColor(QColor(self.settings["border_color"]), self, "테두리 색 지정")
        if color.isValid():
            self.settings["border_color"] = color.name()
            self._refresh_color_button()
            self.overlay.update_settings()
            self.save_settings()

    def show_to_front(self):
        self.show()
        self.raise_()
        self.activateWindow()

    def reset_session(self):
        with self._count_lock:
            self.session_count = 0
        self.count_label.setText("현재 세션 캡처: 0장")
        self.set_status("세션 카운트를 초기화했습니다")

    def quit_app(self):
        self.overlay.save_geometry()
        self.save_settings()
        try:
            keyboard.unhook_all()
        except Exception:
            pass
        self.tray.hide()
        QApplication.quit()

    # ------------------------------------------------------------------ 캡처

    def trigger_capture(self):
        now = time.monotonic()
        if now - self.last_capture_time < self.MIN_CAPTURE_INTERVAL:
            return
        self.last_capture_time = now

        bbox = self.overlay.get_capture_bbox()
        if bbox[2] - bbox[0] < 5 or bbox[3] - bbox[1] < 5:
            return

        threading.Thread(target=self.do_capture, args=(bbox,), daemon=True).start()

    def do_capture(self, bbox):
        try:
            # 테두리가 캡처 이미지에 포함되지 않도록 오버레이를 시그널로 숨김 (메인 스레드 안전)
            self.signals.overlay_hide.emit()
            time.sleep(0.05)  # OS 화면 렌더링 반영 대기

            with mss.mss() as sct:
                monitor = {"top": bbox[1], "left": bbox[0],
                           "width": bbox[2] - bbox[0], "height": bbox[3] - bbox[1]}
                screenshot = sct.grab(monitor)
                img = Image.frombytes("RGB", screenshot.size, screenshot.rgb)

            folder = self.settings["save_folder"]
            os.makedirs(folder, exist_ok=True)

            now = datetime.now()
            with self._count_lock:
                count = self.session_count + 1

            template = self.settings["template"]
            if template == "datetime":
                base_name = f"capture_{now.strftime('%y%m%d_%H%M%S')}"
            elif template == "custom":
                prefix = self.settings["custom_prefix"].strip() or "capture"
                prefix = re.sub(r'[\\/:*?"<>|]', "_", prefix)
                base_name = f"{prefix}_{count:04d}"
            else:  # numbered
                base_name = f"image_{count:03d}_{now.strftime('%H%M%S')}"

            fmt = self.settings["save_format"]
            ext = ".jpg" if fmt == "JPG" else ".png"

            final_path = os.path.join(folder, base_name + ext)
            idx = 1
            while os.path.exists(final_path):
                final_path = os.path.join(folder, f"{base_name} ({idx}){ext}")
                idx += 1

            if fmt == "JPG":
                img.save(final_path, quality=int(self.settings.get("jpg_quality", 95)))
            else:
                img.save(final_path)

            with self._count_lock:
                self.session_count += 1
                current = self.session_count
            self.signals.capture_done.emit(current, os.path.basename(final_path))

        except Exception as e:
            self.signals.capture_failed.emit(str(e))
        finally:
            # 예외 발생 여부와 관계없이 오버레이를 반드시 복원
            self.signals.overlay_show.emit()

    def on_capture_done(self, count, filename):
        self.count_label.setText(f"현재 세션 캡처: {count}장")
        self.set_status(f"저장됨: {filename}")
        self.overlay.flash()

    def on_capture_failed(self, message):
        self.set_status(f"캡처 실패: {message}", error=True)

    def closeEvent(self, event):
        # 설정창을 닫으면 프로그램 종료가 아니라 숨김 (툴바 ✖ 또는 트레이 메뉴로 완전 종료)
        event.ignore()
        self.hide()


def main():
    app = QApplication(sys.argv)
    # 트레이 상주형 — 창이 모두 닫혀도 명시적 종료 전까지 유지
    app.setQuitOnLastWindowClosed(False)
    app.setWindowIcon(QIcon(resource_path("icon.ico")))
    window = CaptureApp()  # noqa: F841 — 참조 유지 필요
    sys.exit(app.exec())


if __name__ == "__main__":
    main()
