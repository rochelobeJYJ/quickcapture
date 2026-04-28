# main.py
import sys
import json
import os
import threading
import time
from datetime import datetime

import ctypes
try:
    ctypes.windll.shcore.SetProcessDpiAwareness(1)
except:
    try:
        ctypes.windll.user32.SetProcessDPIAware()
    except:
        pass

from PyQt6.QtWidgets import (QApplication, QMainWindow, QWidget, QVBoxLayout, 
                             QHBoxLayout, QLabel, QLineEdit, QPushButton, 
                             QComboBox, QCheckBox, QFileDialog, QColorDialog,
                             QGridLayout, QFrame, QDialog)
from PyQt6.QtCore import Qt, QTimer, pyqtSignal, QObject
from PyQt6.QtGui import QColor, QKeySequence

import keyboard
import mss
from PIL import Image

from overlay import OverlayWindow

SETTINGS_FILE = "settings.json"
DEFAULT_FOLDER = r"D:\image_capture"

class Signals(QObject):
    capture_update = pyqtSignal(int)
    overlay_hide = pyqtSignal()
    overlay_show = pyqtSignal()
    do_flash = pyqtSignal()

class HotkeyDialog(QDialog):
    def __init__(self, current_hotkey, parent=None):
        super().__init__(parent)
        self.setWindowTitle("단축키 변경")
        self.setFixedSize(300, 130)
        self.hotkey = None
        self.setStyleSheet("""
            QDialog { background-color: #f7f8fa; }
            QLabel { color: #333333; font-family: 'Malgun Gothic', sans-serif; font-size: 13px; }
        """)
        layout = QVBoxLayout(self)
        
        lbl = QLabel(f"현재 단축키: <b style='color:#0078d4'>{current_hotkey.upper()}</b><br><br>사용할 새로운 단축키를 직접 누르세요.<br>(취소하려면 ESC)")
        lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(lbl)
        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)

    def keyPressEvent(self, event):
        key = event.key()
        modifiers = []
        
        if event.modifiers() & Qt.KeyboardModifier.ControlModifier: modifiers.append("ctrl")
        if event.modifiers() & Qt.KeyboardModifier.AltModifier: modifiers.append("alt")
        if event.modifiers() & Qt.KeyboardModifier.ShiftModifier: modifiers.append("shift")
        
        if key in [Qt.Key.Key_Control, Qt.Key.Key_Shift, Qt.Key.Key_Alt, Qt.Key.Key_Meta]:
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
    def __init__(self):
        super().__init__()
        self.settings = self.load_settings()
        self.last_capture_time = 0
        self.min_interval = 200 # ms
        self.session_count = 0
        
        self.signals = Signals()
        self._count_lock = threading.Lock()
        self.signals.capture_update.connect(self.update_count_ui)

        self.init_ui()
        self.overlay = OverlayWindow(self.settings)
        self.overlay.capture_requested.connect(self.trigger_capture)
        self.overlay.folder_requested.connect(self.open_saved_folder)
        self.overlay.settings_requested.connect(self.show_to_front)
        self.overlay.ontop_toggled.connect(self.ontop_cb.setChecked)
        self.overlay.exit_requested.connect(self.quit_app)
        self.signals.overlay_hide.connect(self.overlay.hide)
        self.signals.overlay_show.connect(self.overlay.show)
        self.signals.do_flash.connect(self.overlay_flash)
        self.overlay.show()
        
        self.register_hotkey()

    def load_settings(self):
        if os.path.exists(SETTINGS_FILE):
            try:
                with open(SETTINGS_FILE, "r", encoding="utf-8") as f:
                    return json.load(f)
            except:
                pass
        return {
            "save_folder": DEFAULT_FOLDER,
            "hotkey": "ctrl+shift+c",
            "border_color": "#ff4d4d",
            "border_thickness": 4,
            "overlay_x": 300,
            "overlay_y": 200,
            "overlay_width": 600,
            "overlay_height": 400,
            "always_on_top": True,
            "save_format": "PNG",
            "custom_prefix": "capture",
            "template": "image_{:03d}_HHMMSS.png"
        }

    def save_settings(self):
        try:
            with open(SETTINGS_FILE, "w", encoding="utf-8") as f:
                json.dump(self.settings, f, ensure_ascii=False, indent=2)
        except:
            pass

    def init_ui(self):
        self.setWindowTitle("QuickCapture Pro")
        self.setFixedSize(450, 480)
        
        font_family = "'Pretendard', 'Malgun Gothic', sans-serif"
        
        self.setStyleSheet(f"""
            QMainWindow {{ background-color: #f0f2f5; }}
            QLabel {{ color: #333333; font-family: {font_family}; font-size: 13px; font-weight: bold; }}
            QLineEdit, QComboBox {{ 
                background-color: #ffffff; color: #333333; 
                border: 1px solid #d1d5db; border-radius: 5px; 
                padding: 5px 10px; font-size: 12px; font-family: {font_family};
            }}
            QLineEdit:read-only {{ background-color: #f9fafb; color: #6b7280; }}
            QPushButton {{ 
                background-color: #0078d4; color: #ffffff; 
                border: none; border-radius: 5px; 
                padding: 6px 14px; font-weight: bold; font-size: 12px; font-family: {font_family};
            }}
            QPushButton:hover {{ background-color: #106ebe; }}
            QPushButton:pressed {{ background-color: #005a9e; }}
            QPushButton#light_btn {{ background-color: #e5e7eb; color: #374151; }}
            QPushButton#light_btn:hover {{ background-color: #d1d5db; }}
            
            QCheckBox {{ color: #333333; font-size: 13px; font-weight: bold; font-family: {font_family}; }}
            QFrame#card {{ background-color: #ffffff; border-radius: 8px; border: 1px solid #e5e7eb; }}
            QComboBox::drop-down {{ border: 0px; width: 20px; }}
            QComboBox::down-arrow {{ image: none; }}
        """)

        central_widget = QWidget()
        self.setCentralWidget(central_widget)
        main_layout = QVBoxLayout(central_widget)
        main_layout.setContentsMargins(15, 15, 15, 15)
        main_layout.setSpacing(10)

        title_label = QLabel("QUICK CAPTURE")
        title_label.setStyleSheet(f"font-size: 20px; font-weight: 900; color: #1f2937; letter-spacing: 1px; font-family: {font_family};")
        main_layout.addWidget(title_label, alignment=Qt.AlignmentFlag.AlignCenter)

        card = QFrame()
        card.setObjectName("card")
        card_layout = QGridLayout(card)
        card_layout.setContentsMargins(20, 20, 20, 20)
        card_layout.setVerticalSpacing(15)
        card_layout.setHorizontalSpacing(12)

        card_layout.addWidget(QLabel("저장 폴더"), 0, 0)
        self.folder_input = QLineEdit(self.settings["save_folder"])
        self.folder_input.setReadOnly(True)
        card_layout.addWidget(self.folder_input, 0, 1)
        folder_btn = QPushButton("폴더 변경")
        folder_btn.setObjectName("light_btn")
        folder_btn.clicked.connect(self.change_folder)
        card_layout.addWidget(folder_btn, 0, 2)

        card_layout.addWidget(QLabel("단축키"), 1, 0)
        self.hotkey_btn = QPushButton(self.settings.get("hotkey", "ctrl+shift+c").upper())
        self.hotkey_btn.clicked.connect(self.change_hotkey)
        card_layout.addWidget(self.hotkey_btn, 1, 1, 1, 2)

        card_layout.addWidget(QLabel("저장 포맷"), 2, 0)
        self.format_combo = QComboBox()
        self.format_combo.addItems(["PNG", "JPG"])
        self.format_combo.setCurrentText(self.settings.get("save_format", "PNG"))
        self.format_combo.currentTextChanged.connect(self.update_format)
        card_layout.addWidget(self.format_combo, 2, 1, 1, 2)

        card_layout.addWidget(QLabel("파일명 양식"), 3, 0)
        self.template_combo = QComboBox()
        self.template_combo.addItems([
            "image_{:03d}_HHMMSS.png",
            "capture_{YYMMDD_HHMMSS}.png",
            "직접 지정한 이름_{:04d}.png"
        ])
        saved_templ = self.settings.get("template", "image_{:03d}_HHMMSS.png")
        if saved_templ == "{custom}_{:04d}.png":
            self.template_combo.setCurrentText("직접 지정한 이름_{:04d}.png")
        else:
            self.template_combo.setCurrentText(saved_templ)
        self.template_combo.currentTextChanged.connect(self.update_template)
        card_layout.addWidget(self.template_combo, 3, 1, 1, 2)

        card_layout.addWidget(QLabel("직접 지정 이름"), 4, 0)
        self.prefix_input = QLineEdit(self.settings.get("custom_prefix", "capture"))
        self.prefix_input.textChanged.connect(self.update_prefix)
        self.prefix_input.setPlaceholderText("양식 3번을 선택했을 때 사용됩니다")
        card_layout.addWidget(self.prefix_input, 4, 1, 1, 2)

        self.ontop_cb = QCheckBox("오버레이 창을 항상 맨 위에 표시")
        self.ontop_cb.setChecked(self.settings.get("always_on_top", True))
        self.ontop_cb.stateChanged.connect(self.toggle_ontop)
        card_layout.addWidget(self.ontop_cb, 5, 0, 1, 3)

        main_layout.addWidget(card)

        bottom_layout = QHBoxLayout()
        stat_card = QFrame()
        stat_card.setStyleSheet("background-color: #ffffff; border-radius: 5px; border: 1px solid #e5e7eb;")
        stat_layout = QHBoxLayout(stat_card)
        stat_layout.setContentsMargins(10, 5, 10, 5)
        
        self.count_label = QLabel(f"현재 세션 캡처: {self.session_count}장")
        self.count_label.setStyleSheet("color: #0078d4; font-weight: bold;")
        stat_layout.addWidget(self.count_label)
        
        open_folder_btn = QPushButton("저장 폴더 열기")
        open_folder_btn.setObjectName("light_btn")
        open_folder_btn.clicked.connect(self.open_saved_folder)
        stat_layout.addWidget(open_folder_btn)
        
        bottom_layout.addWidget(stat_card, stretch=6)

        border_btn = QPushButton("오버레이 테두리색")
        border_btn.setObjectName("light_btn")
        border_btn.clicked.connect(self.change_border)
        bottom_layout.addWidget(border_btn, stretch=4)
        
        main_layout.addLayout(bottom_layout)

    def update_count_ui(self, val):
        self.count_label.setText(f"현재 세션 캡처: {val}장")

    def change_folder(self):
        folder = QFileDialog.getExistingDirectory(self, "저장 폴더 선택", self.settings["save_folder"])
        if folder:
            self.settings["save_folder"] = folder
            self.folder_input.setText(folder)
            os.makedirs(folder, exist_ok=True)
            self.save_settings()
            
    def open_saved_folder(self):
        folder = self.settings.get("save_folder", "")
        if os.path.exists(folder):
            os.startfile(folder)

    def change_hotkey(self):
        keyboard.unhook_all()
        dialog = HotkeyDialog(self.settings.get("hotkey", "ctrl+shift+c"), self)
        if dialog.exec() == QDialog.DialogCode.Accepted and dialog.hotkey:
            self.settings["hotkey"] = dialog.hotkey
            self.hotkey_btn.setText(self.settings["hotkey"].upper())
            self.save_settings()
        self.register_hotkey()

    def register_hotkey(self):
        try:
            keyboard.remove_all_hotkeys()
        except:
            pass
        hk = self.settings.get("hotkey", "ctrl+shift+c")
        try:
            keyboard.add_hotkey(hk, self.trigger_capture, suppress=True)
        except ValueError:
            pass

    def update_format(self, text):
        self.settings["save_format"] = text
        self.save_settings()

    def update_template(self, text):
        if text.startswith("직접 지정한"):
            self.settings["template"] = "{custom}_{:04d}.png"
        else:
            self.settings["template"] = text
        self.save_settings()

    def update_prefix(self, text):
        self.settings["custom_prefix"] = text
        self.save_settings()

    def toggle_ontop(self, state):
        val = Qt.CheckState(state) == Qt.CheckState.Checked
        self.settings["always_on_top"] = val
        self.overlay.set_always_on_top(val)
        self.save_settings()

    def change_border(self):
        color = QColorDialog.getColor(QColor(self.settings.get("border_color", "#ff4d4d")), self, "테두리 색 지정")
        if color.isValid():
            self.settings["border_color"] = color.name()
            self.overlay.update_settings()
            self.save_settings()

    def show_to_front(self):
        self.show()
        self.raise_()
        self.activateWindow()

    def quit_app(self):
        self.overlay.save_geometry()
        self.save_settings()
        keyboard.unhook_all()
        QApplication.quit()

    def trigger_capture(self):
        now = time.time()
        if (now - self.last_capture_time) * 1000 < self.min_interval:
            return
        self.last_capture_time = now

        bbox = self.overlay.get_capture_bbox()
        if bbox[2] - bbox[0] < 5 or bbox[3] - bbox[1] < 5:
            return

        threading.Thread(target=self.do_capture, args=(bbox,), daemon=True).start()

    def do_capture(self, bbox):
        img = None
        try:
            # 테두리가 캡처 이미지에 포함되지 않도록 오버레이를 시그널로 숨김 (메인 스레드 안전)
            self.signals.overlay_hide.emit()
            time.sleep(0.05)  # OS 화면 렌더링 반영 대기

            with mss.mss() as sct:
                monitor = {"top": bbox[1], "left": bbox[0], "width": bbox[2]-bbox[0], "height": bbox[3]-bbox[1]}
                screenshot = sct.grab(monitor)
                img = Image.frombytes("RGB", screenshot.size, screenshot.rgb)

            folder = self.settings["save_folder"]
            os.makedirs(folder, exist_ok=True)

            template = self.settings.get("template", "image_{:03d}_HHMMSS.png")
            now = datetime.now()
            with self._count_lock:
                count = self.session_count + 1

            if "HHMMSS" in template and "YYMMDD" not in template:
                filename = f"image_{count:03d}_{now.strftime('%H%M%S')}.png"
            elif "YYMMDD" in template:
                filename = f"capture_{now.strftime('%y%m%d_%H%M%S')}.png"
            else:
                prefix = self.settings.get("custom_prefix", "capture").strip() or "capture"
                filename = f"{prefix}_{count:04d}.png"

            fmt = self.settings.get("save_format", "PNG")
            ext = ".png" if fmt == "PNG" else ".jpg"
            if not filename.lower().endswith((".png", ".jpg")):
                filename = filename.rsplit(".", 1)[0] + ext

            base_name, ext = os.path.splitext(filename)
            final_path = os.path.join(folder, filename)
            idx = 1
            while os.path.exists(final_path):
                final_path = os.path.join(folder, f"{base_name} ({idx}){ext}")
                idx += 1

            img.save(final_path, quality=95 if fmt == "JPG" else None)

            with self._count_lock:
                self.session_count += 1
                current = self.session_count
            self.signals.capture_update.emit(current)
            self.signals.do_flash.emit()

        except Exception:
            pass
        finally:
            # 예외 발생 여부와 관계없이 오버레이를 반드시 복원
            self.signals.overlay_show.emit()
            
    def overlay_flash(self):
        old_color = self.overlay.border_color
        self.overlay.border_color = "#ffffff"
        self.overlay.update()
        QTimer.singleShot(100, lambda: self._revert_flash(old_color))
        
    def _revert_flash(self, old_color):
        self.overlay.border_color = old_color
        self.overlay.update()

    def closeEvent(self, event):
        # Settings 창을 끄면 아예 프로그램이 종료되는게 아니라 숨김처리만 (툴바에서 ❌를 눌러서 완전종료)
        event.ignore()
        self.hide()


if __name__ == "__main__":
    app = QApplication(sys.argv)
    # 마지막 창(오버레이)가 닫힐 때 완전히 종료되도록 유지
    app.setQuitOnLastWindowClosed(True)
    window = CaptureApp()
    # window.show() <- 제거됨. 처음에 캡처 영역만 뜸!
    sys.exit(app.exec())