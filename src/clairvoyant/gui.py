from typing import Optional
from PySide6.QtWidgets import (
    QApplication,
    QWidget,
    QVBoxLayout,
    QPushButton,
    QFileDialog,
    QMessageBox,
    QLabel,
    QPlainTextEdit,
    QHBoxLayout,
    QLineEdit,
    QCheckBox,
    QToolButton,
    QDialog,
    QTextEdit,
)
from PySide6.QtCore import Qt, Signal, QThread, QTimer
from PySide6.QtGui import QIcon, QCursor
import os
import sys
from . import stego, crypto

def resource_path(relative_path):
    base_path = getattr(sys, '_MEIPASS', os.path.dirname(os.path.abspath(__file__)))
    return os.path.join(base_path, relative_path)

class Worker(QThread):
    done = Signal()
    error = Signal(str)

    def __init__(self, fn, *args, **kwargs):
        super().__init__()
        self.fn = fn
        self.args = args
        self.kwargs = kwargs

    def run(self):
        try:
            res = self.fn(*self.args, **self.kwargs)
            self.result = res
            self.done.emit()
        except Exception as e:
            self.error.emit(str(e))


class MainWindow(QWidget):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("Clairvoyant, your local steganographer")
        self.resize(700, 420)

        layout = QVBoxLayout()

        hl = QHBoxLayout()
        self.open_btn = QPushButton("Select Image/Video")
        self.open_btn.clicked.connect(self.open_image)
        hl.addWidget(self.open_btn)

        self.embed_btn = QPushButton("Embed")
        self.embed_btn.clicked.connect(self.embed_message)
        hl.addWidget(self.embed_btn)

        self.extract_btn = QPushButton("Extract")
        self.extract_btn.clicked.connect(self.extract_message)
        hl.addWidget(self.extract_btn)

        layout.addLayout(hl)

        layout.addWidget(QLabel("Selected file:"))
        # highlight selected path
        self.file_label = QLabel("(none)")
        self.file_label.setStyleSheet("font-weight: bold;")
        layout.addWidget(self.file_label)

        # message label and metrics on same row
        top_h = QHBoxLayout()
        top_h.addWidget(QLabel("Payload to embed:"))
        top_h.addStretch()
        right_v = QVBoxLayout()
        self.msg_size_label = QLabel("Message size: 0 bytes")
        self.cap_used_label = QLabel("Capacity used: 0%")
        self.msg_size_label.setAlignment(Qt.AlignRight)
        self.cap_used_label.setAlignment(Qt.AlignRight)
        right_v.addWidget(self.msg_size_label)
        right_v.addWidget(self.cap_used_label)
        top_h.addLayout(right_v)
        layout.addLayout(top_h)

        self.msg_edit = QPlainTextEdit()
        self.msg_edit.textChanged.connect(self._update_message_metrics)
        layout.addWidget(self.msg_edit)

        h2 = QHBoxLayout()
        h2.addWidget(QLabel("Passphrase:"))
        self.pass_edit = QLineEdit()
        self.pass_edit.setEchoMode(QLineEdit.Password)
        self.pass_edit.setEnabled(False)
        h2.addWidget(self.pass_edit)
        # show/Hide text button (fixed width)
        self.eye_btn = QToolButton()
        self.eye_btn.setText("Show")
        self.eye_btn.setEnabled(False)
        self.eye_btn.setToolTip("Show / hide passphrase")
        self.eye_btn.setFixedWidth(60)
        self.eye_btn.setStyleSheet("text-align:center;")
        self.eye_btn.clicked.connect(self._toggle_pass_visible)
        h2.addWidget(self.eye_btn)
        self.encrypt_cb = QCheckBox("Encrypt payload (AES-GCM)")
        self.encrypt_cb.stateChanged.connect(self._on_encrypt_toggled)
        h2.addWidget(self.encrypt_cb)
        layout.addLayout(h2)

        # capacity information 
        cap_h = QHBoxLayout()
        cap_h.addWidget(QLabel("Capacity estimate:"))
        self.capacity_label = QLabel("(open a file to see capacity)")
        cap_h.addWidget(self.capacity_label)
        info = QLabel("what's this?")
        info.setStyleSheet("font-weight: bold; text-decoration: underline; color: #0645AD;")
        info.setCursor(QCursor(Qt.PointingHandCursor))
        cap_h.addWidget(info)
        # allow clicking the info label to show a dialog with capacity details, for the confused user
        def _info_clicked(ev):
            dlg = QDialog(self)
            dlg.setWindowTitle("Capacity details")
            v = QVBoxLayout(dlg)
            te = QTextEdit()
            te.setReadOnly(True)
            te.setPlainText("Capacity estimate = number of pixels * 3 color bytes * 1 bit per byte, minus header.\nShown value is approximate available payload bytes.")
            v.addWidget(te)
            b = QPushButton("OK")
            b.clicked.connect(dlg.accept)
            v.addWidget(b)
            dlg.exec()
        info.mouseReleaseEvent = _info_clicked
        cap_h.setAlignment(Qt.AlignLeft)
        layout.addLayout(cap_h)

        # video mode: choose append vs LSB-in-frame
        self.video_lsb_cb = QCheckBox("Use LSB-in-frame mode for videos (experimental)")
        self.video_lsb_cb.setToolTip(
            "When enabled, embedding will try to hide bits in per-frame pixel LSBs. "
            "This only survives lossless codecs and is fragile."
        )
        layout.addWidget(self.video_lsb_cb)

        self.setLayout(layout)
        self.current_path: Optional[str] = None

    def open_image(self):
        path, _ = QFileDialog.getOpenFileName(
            self,
            "Open file",
            "",
            "Images and Videos (*.png *.bmp *.jpg *.jpeg *.mp4 *.avi *.mov *.mkv)",
        )
        if path:
            self.current_path = path
            self.file_label.setText(path)
            # estimate capacity
            try:
                if path.lower().endswith((".mp4", ".avi", ".mov", ".mkv")):
                        if getattr(self, 'video_lsb_cb', None) and self.video_lsb_cb.isChecked():
                            cap = stego.estimate_video_capacity_lsb(path)
                        else:
                            cap = stego.estimate_video_capacity(path)
                else:
                    cap = stego.estimate_image_capacity(path)
                self.capacity_label.setText(f"~{cap} bytes")
            except Exception:
                self.capacity_label.setText("(unable to estimate)")
            # update message metrics when opening a new file
            self._update_message_metrics()

    def _show_text_dialog(self, title: str, text: str):
        dlg = QDialog(self)
        dlg.setWindowTitle(title)
        v = QVBoxLayout(dlg)
        te = QTextEdit()
        te.setReadOnly(True)
        te.setPlainText(text)
        v.addWidget(te)
        b = QPushButton("OK")
        b.clicked.connect(dlg.accept)
        v.addWidget(b)
        dlg.exec()

    def _toggle_pass_visible(self):
        visible = getattr(self, "pass_visible", False)
        visible = not visible
        self.pass_visible = visible
        if visible:
            self.pass_edit.setEchoMode(QLineEdit.Normal)
            self.eye_btn.setText("Hide")
        else:
            self.pass_edit.setEchoMode(QLineEdit.Password)
            self.eye_btn.setText("Show")

    def _on_encrypt_toggled(self, state):
        enabled = bool(state)
        self.pass_edit.setEnabled(enabled)
        self.eye_btn.setEnabled(enabled)
        if not enabled:
            self.pass_edit.setEchoMode(QLineEdit.Password)
            self.pass_visible = False
            self.eye_btn.setText("Show")

    def embed_message(self):
        if not self.current_path:
            QMessageBox.warning(self, "No file", "Please select an image or video first.")
            return
        text = self.msg_edit.toPlainText().encode("utf-8")
        # optional encryption
        if self.encrypt_cb.isChecked():
            pw = self.pass_edit.text()
            if not pw:
                QMessageBox.warning(self, "Passphrase required", "Please enter a passphrase to encrypt.")
                return
            text = crypto.encrypt(text, pw)

        # compute capacity (for display only)
        try:
            if self.current_path.lower().endswith((".mp4", ".avi", ".mov", ".mkv")):
                cap_bytes = stego.estimate_video_capacity(self.current_path)
            else:
                cap_bytes = stego.estimate_image_capacity(self.current_path)
        except Exception:
            cap_bytes = None

        try:
            # suggest output extension matching input type
            if self.current_path.lower().endswith((".mp4", ".avi", ".mov", ".mkv")):
                default = "stego.mp4"
                flt = "Video Files (*.mp4 *.avi *.mov *.mkv)"
            else:
                default = "stego.png"
                flt = "PNG Image (*.png);;All Files (*)"
            suggested, _ = QFileDialog.getSaveFileName(self, "Save stego file as", default, flt)
            if not suggested:
                return
            # run embedding in background for videos to avoid blocking UI
            if self.current_path.lower().endswith((".mp4", ".avi", ".mov", ".mkv")):
                # choose video embed function based on LSB checkbox
                if getattr(self, 'video_lsb_cb', None) and self.video_lsb_cb.isChecked():
                    embed_fn = stego.embed_message_into_video_lsb
                else:
                    embed_fn = stego.embed_message_into_video
                # keep reference to worker to avoid GC and premature destruction
                self._worker_embed = Worker(embed_fn, self.current_path, suggested, text)
                self._disable_ui()
                self._worker_embed.done.connect(lambda: self._on_embed_finished(suggested))
                self._worker_embed.error.connect(self._on_worker_error)
                self._worker_embed.start()
            else:
                stego.embed_message_into_image(self.current_path, suggested, text)
                QMessageBox.information(self, "Success", "Message embedded and file saved.")
        except Exception as e:
            QMessageBox.critical(self, "Error", str(e))

    def extract_message(self):
        if not self.current_path:
            QMessageBox.warning(self, "No file", "Please select an image or video first.")
            return
        try:
            if self.current_path.lower().endswith((".mp4", ".avi", ".mov", ".mkv")):
                if getattr(self, 'video_lsb_cb', None) and self.video_lsb_cb.isChecked():
                    extract_fn = stego.extract_message_from_video_lsb
                else:
                    extract_fn = stego.extract_message_from_video
                self._worker_extract = Worker(extract_fn, self.current_path)
                self._disable_ui()
                self._worker_extract.done.connect(self._on_extract_finished)
                self._worker_extract.error.connect(self._on_worker_error)
                self._worker_extract.start()
            else:
                data = stego.extract_message_from_image(self.current_path)
                try:
                    if self.pass_edit.text():
                        try:
                            data = crypto.decrypt(data, self.pass_edit.text())
                        except Exception:
                            pass
                    text = data.decode("utf-8")
                except Exception:
                    text = repr(data)
                self._show_text_dialog("Extracted message", text)
        except Exception as e:
            QMessageBox.critical(self, "Error", str(e))

    def _on_embed_finished(self, path: str):
        # clear worker reference
        try:
            self._worker_embed = None
        except AttributeError:
            pass
        self._enable_ui()
        QMessageBox.information(self, "Success", f"Message embedded and file saved: {path}")

    def _on_extract_finished(self):
        # get result from worker
        data = getattr(self._worker_extract, 'result', None)
        # clear worker reference
        try:
            self._worker_extract = None
        except AttributeError:
            pass
        self._enable_ui()
        # prevent duplicate extract dialogs
        if getattr(self, '_extract_dialog_shown', False):
            return
        self._extract_dialog_shown = True
        QTimer.singleShot(1000, lambda: setattr(self, '_extract_dialog_shown', False))

        # If no payload found
        if not data:
            QMessageBox.information(self, "Extracted message", "No embedded message found.")
            return
        try:
            if self.pass_edit.text():
                try:
                    data = crypto.decrypt(data, self.pass_edit.text())
                except Exception:
                    pass
            text = data.decode("utf-8")
        except Exception:
            text = repr(data)
        QMessageBox.information(self, "Extracted message", text)

    def _on_worker_error(self, err: str):
        self._enable_ui()
        QMessageBox.critical(self, "Error", err)

    def _disable_ui(self):
        self.open_btn.setEnabled(False)
        self.embed_btn.setEnabled(False)
        self.extract_btn.setEnabled(False)

    def _enable_ui(self):
        self.open_btn.setEnabled(True)
        self.embed_btn.setEnabled(True)
        self.extract_btn.setEnabled(True)

    def _update_message_metrics(self):
        text = self.msg_edit.toPlainText().encode("utf-8")
        size = len(text)
        self.msg_size_label.setText(f"Message size: {size} bytes")
        try:
            if self.current_path and self.current_path.lower().endswith((".mp4", ".avi", ".mov", ".mkv")):
                cap_bytes = stego.estimate_video_capacity(self.current_path)
            elif self.current_path:
                cap_bytes = stego.estimate_image_capacity(self.current_path)
            else:
                cap_bytes = None
        except Exception:
            cap_bytes = None
        if cap_bytes:
            pct = size * 100 / cap_bytes
            self.cap_used_label.setText(f"Capacity used: {pct:.1f}%")
        else:
            self.cap_used_label.setText("Capacity used: N/A")


def main():
    app = QApplication([])
    # load application icon 
    icon_path = resource_path("assets/icon.png")
    if os.path.exists(icon_path):
        app.setWindowIcon(QIcon(icon_path))

    w = MainWindow()
    w.setWindowIcon(QIcon(icon_path))
    w.show()
    app.exec()