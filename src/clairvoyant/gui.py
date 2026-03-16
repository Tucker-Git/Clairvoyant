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

class MessageEditBox(QPlainTextEdit):
    """custom text edit that warns about large pastes."""
    paste_started = Signal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self.main_window = None

    def insertFromMimeData(self, source):
        """intercept paste to warn about large content."""
        # check if clipboard has text and estimate size
        if source.hasText():
            text = source.text()
            if len(text) > 100000:  # 100KB threshold
                # create custom dialog with centered layout
                dlg = QDialog(self.window())
                dlg.setWindowTitle("Large paste detected")
                dlg.setModal(True)
                layout = QVBoxLayout(dlg)

                msg = QLabel(f"Pasting {len(text):,} bytes will cause the app to hang for several seconds.\n\nUse the .txt file feature instead?")
                msg.setAlignment(Qt.AlignCenter)
                layout.addWidget(msg)

                # centered button layout
                btn_layout = QHBoxLayout()
                btn_layout.addStretch()
                yes_btn = QPushButton("Yes, use .txt file")
                no_btn = QPushButton("No, continue")
                cancel_btn = QPushButton("Cancel")
                yes_btn.clicked.connect(dlg.accept)
                no_btn.clicked.connect(lambda: dlg.done(1))
                cancel_btn.clicked.connect(dlg.reject)
                btn_layout.addWidget(yes_btn)
                btn_layout.addWidget(no_btn)
                btn_layout.addWidget(cancel_btn)
                btn_layout.addStretch()
                layout.addLayout(btn_layout)

                result = dlg.exec()
                if result == QDialog.Accepted:  # Yes button
                    if self.main_window:
                        self.main_window._load_payload_file()
                    return
                elif result == QDialog.Rejected:  # Cancel
                    return
                # else: No button (result == 1), proceed with paste
        # insert the text
        super().insertFromMimeData(source)

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
        self.load_txt_btn = QPushButton("Embed .txt file")
        self.load_txt_btn.setMaximumWidth(150)
        top_h.addWidget(self.load_txt_btn)
        self.load_txt_btn.clicked.connect(self._load_payload_file)
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

        self.msg_edit = MessageEditBox()
        self.msg_edit.main_window = self
        self.msg_edit.textChanged.connect(self._update_message_metrics)
        layout.addWidget(self.msg_edit)

        # label to show selected file with clear button
        file_h = QHBoxLayout()
        self.selected_file_label = QLabel("")
        self.selected_file_label.setStyleSheet("color: #666; font-style: italic;")
        file_h.addWidget(self.selected_file_label)
        self.clear_file_btn = QPushButton("Clear")
        self.clear_file_btn.setMaximumWidth(70)
        self.clear_file_btn.clicked.connect(self._clear_payload_file)
        self.clear_file_btn.setVisible(False)
        file_h.addWidget(self.clear_file_btn)
        file_h.addStretch()
        layout.addLayout(file_h)

        h2 = QHBoxLayout()
        h2.addWidget(QLabel("Passphrase:"))
        self.pass_edit = QLineEdit()
        self.pass_edit.setEchoMode(QLineEdit.Password)
        self.pass_edit.setEnabled(False)
        h2.addWidget(self.pass_edit)
        # show/hide text button (fixed width)
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
        # allow clicking the info label to show a dialog with capacity details
        def _info_clicked(ev):
            dlg = QDialog(self)
            dlg.setWindowTitle("Capacity details")
            v = QVBoxLayout(dlg)
            te = QTextEdit()
            te.setReadOnly(True)
            te.setPlainText(
                "Capacity varies by method:\n\n"
                "1. IMAGES (LSB mode):\n"
                "   Capacity = (width × height × 3 color channels × 1 bit per channel) - header\n"
                "   Fixed limit based on image dimensions.\n\n"
                "2. VIDEOS (default append mode):\n"
                "   Capacity = UNLIMITED\n"
                "   Message is appended to the video file. You can embed any size payload.\n"
                "   Output file size = original size + message size.\n\n"
                "3. VIDEOS (LSB mode):\n"
                "   Capacity = (frame count × width × height × 3 channels × 1 bit) - header\n"
                "   Limited by video frame count and resolution.\n"
                "   Only survives lossless codecs.\n\n"
                "Toggle LSB mode for videos to see capacity switch between unlimited and frame-based estimates."
            )
            v.addWidget(te)
            b = QPushButton("OK")
            b.clicked.connect(dlg.accept)
            v.addWidget(b)
            dlg.exec()
        info.mouseReleaseEvent = _info_clicked
        cap_h.setAlignment(Qt.AlignLeft)
        layout.addLayout(cap_h)

        # video mode: choose append vs LSB-in-frame
        lsb_h = QHBoxLayout()
        self.video_lsb_cb = QCheckBox("Use LSB-in-frame mode for videos (experimental)")
        lsb_h.addWidget(self.video_lsb_cb)
        lsb_info = QLabel("what's this?")
        lsb_info.setStyleSheet("font-weight: bold; text-decoration: underline; color: #0645AD;")
        lsb_info.setCursor(QCursor(Qt.PointingHandCursor))
        lsb_h.addWidget(lsb_info)
        lsb_h.addStretch()
        # allow clicking the info label to show a dialog with LSB details
        def _lsb_info_clicked(ev):
            dlg = QDialog(self)
            dlg.setWindowTitle("LSB mode details")
            v = QVBoxLayout(dlg)
            te = QTextEdit()
            te.setReadOnly(True)
            te.setPlainText(
                "When enabled, embedding will try to hide bits in per-frame pixel LSBs. "
                "This only survives lossless codecs and is fragile.\n\n"
                "For best results, use .mkv output format. "
                "On Windows, h264-encoded MP4 files may have codec issues.\n\n"
                "Recommended: use the default append mode unless you specifically need LSB embedding."
            )
            v.addWidget(te)
            b = QPushButton("OK")
            b.clicked.connect(dlg.accept)
            v.addWidget(b)
            dlg.exec()
        lsb_info.mouseReleaseEvent = _lsb_info_clicked
        layout.addLayout(lsb_h)
        # connect LSB checkbox to update capacity estimates
        self.video_lsb_cb.stateChanged.connect(self._on_lsb_mode_toggled)

        self.setLayout(layout)
        self.current_path: Optional[str] = None
        self.pass_visible = False
        self.cached_capacity: Optional[int] = None  # cache capacity to avoid recalculating on every keystroke
        self.payload_file: Optional[str] = None  # path to selected .txt payload file

    def _is_video(self, path: str) -> bool:
        """check if path is a video file."""
        return path.lower().endswith((".mp4", ".avi", ".mov", ".mkv"))

    def _update_extract_button_state(self):
        """disable extract button if LSB mode is enabled with MP4 input."""
        if not self.current_path:
            self.extract_btn.setEnabled(False)
            self.extract_btn.setToolTip("")
            return

        is_lsb_mode = getattr(self, 'video_lsb_cb', None) and self.video_lsb_cb.isChecked()
        is_mp4 = self.current_path.lower().endswith('.mp4')

        # disable if trying to extract LSB from MP4
        if is_lsb_mode and is_mp4:
            self.extract_btn.setEnabled(False)
            self.extract_btn.setToolTip("LSB extraction is not compatible with h264-encoded MP4 files on Windows. Convert to .mkv format first.")
        else:
            self.extract_btn.setEnabled(True)
            self.extract_btn.setToolTip("")

    def _on_lsb_mode_toggled(self):
        """update capacity estimates when LSB mode is toggled."""
        if self.current_path and self._is_video(self.current_path):
            try:
                if self.video_lsb_cb.isChecked():
                    cap = stego.estimate_video_capacity_lsb(self.current_path)
                else:
                    cap = stego.estimate_video_capacity(self.current_path)
                self.cached_capacity = cap
                if cap == -1:
                    self.capacity_label.setText("(unlimited - append mode)")
                else:
                    self.capacity_label.setText(f"~{cap} bytes")
            except Exception:
                self.capacity_label.setText("(unable to estimate)")
                self.cached_capacity = None
            # update message metrics with new capacity
            self._update_message_metrics()
        # update extract button availability
        self._update_extract_button_state()

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
            # estimate capacity and populate cache
            try:
                if self._is_video(path):
                    if getattr(self, 'video_lsb_cb', None) and self.video_lsb_cb.isChecked():
                        cap = stego.estimate_video_capacity_lsb(path)
                    else:
                        cap = stego.estimate_video_capacity(path)
                else:
                    cap = stego.estimate_image_capacity(path)
                self.cached_capacity = cap
                if cap == -1:
                    self.capacity_label.setText("(unlimited - append mode)")
                else:
                    self.capacity_label.setText(f"~{cap} bytes")
            except Exception:
                self.capacity_label.setText("(unable to estimate)")
                self.cached_capacity = None
            # update message metrics when opening a new file
            self._update_message_metrics()
            # update extract button availability
            self._update_extract_button_state()

    def _load_payload_file(self):
        """open file dialog to select a .txt file as payload."""
        path, _ = QFileDialog.getOpenFileName(
            self,
            "Select text file as payload",
            "",
            "Text Files (*.txt);;All Files (*)",
        )
        if path:
            try:
                # verify file can be read
                with open(path, 'r', encoding='utf-8') as f:
                    file_content = f.read()
                    file_size = len(file_content.encode('utf-8'))
                self.payload_file = path
                # disable textbox to prevent confusion
                self.msg_edit.setEnabled(False)
                # show selected file info
                fname = os.path.basename(path)
                self.selected_file_label.setText(f"{fname} selected as payload")
                self.clear_file_btn.setVisible(True)
                # update size label with file size
                self.msg_size_label.setText(f"Message size: {file_size} bytes")
                # update capacity if we have a file open
                if self.cached_capacity is not None:
                    if self.cached_capacity == -1:
                        self.cap_used_label.setText("Capacity used: (unlimited)")
                    elif self.cached_capacity > 0:
                        pct = file_size * 100 / self.cached_capacity
                        self.cap_used_label.setText(f"Capacity used: {pct:.1f}%")
            except Exception as e:
                QMessageBox.critical(self, "Error", f"Failed to read file: {e}")

    def _clear_payload_file(self):
        """clear the selected payload file and re-enable textbox."""
        self.payload_file = None
        self.msg_edit.setEnabled(True)
        self.selected_file_label.setText("")
        self.clear_file_btn.setVisible(False)
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

    def _show_extracted_message(self, data: bytes):
        """decrypt (if passphrase set) and display extracted message."""
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

    def _toggle_pass_visible(self):
        self.pass_visible = not self.pass_visible
        if self.pass_visible:
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
        # get payload from file or textbox
        if self.payload_file:
            try:
                with open(self.payload_file, 'r', encoding='utf-8') as f:
                    text = f.read().encode("utf-8")
            except Exception as e:
                QMessageBox.critical(self, "Error", f"Failed to read payload file: {e}")
                return
        else:
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
            if self._is_video(self.current_path):
                cap_bytes = stego.estimate_video_capacity(self.current_path)
            else:
                cap_bytes = stego.estimate_image_capacity(self.current_path)
        except Exception:
            cap_bytes = None

        try:
            # suggest output extension matching input type
            if self._is_video(self.current_path):
                # check if using LSB mode with MP4 input - recommend MKV to avoid h264 codec issues
                is_lsb_mode = getattr(self, 'video_lsb_cb', None) and self.video_lsb_cb.isChecked()
                is_mp4_input = self.current_path.lower().endswith('.mp4')

                if is_lsb_mode and is_mp4_input:
                    QMessageBox.information(
                        self,
                        "MKV recommended",
                        "LSB mode with MP4 files can cause extraction issues on Windows.\n\n"
                        "Output will be saved as .mkv for better compatibility."
                    )
                    default = "stego.mkv"
                else:
                    default = "stego.mp4"
                flt = "Video Files (*.mp4 *.avi *.mov *.mkv)"
            else:
                default = "stego.png"
                flt = "PNG Image (*.png);;All Files (*)"
            suggested, _ = QFileDialog.getSaveFileName(self, "Save stego file as", default, flt)
            if not suggested:
                return
            # run embedding in background for videos to avoid blocking UI
            if self._is_video(self.current_path):
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
            if self._is_video(self.current_path):
                # warn if trying to extract LSB from MP4 (h264 codec issues on Windows)
                if getattr(self, 'video_lsb_cb', None) and self.video_lsb_cb.isChecked():
                    is_mp4 = self.current_path.lower().endswith('.mp4')
                    if is_mp4:
                        reply = QMessageBox.warning(
                            self,
                            "MP4 not recommended for LSB extraction",
                            "Extracting from h264-encoded MP4 files can cause the app to hang on Windows.\n\n"
                            "Consider converting the file to .mkv format first.\n\n"
                            "Continue anyway?",
                            QMessageBox.Yes | QMessageBox.No
                        )
                        if reply == QMessageBox.No:
                            return
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
                self._show_extracted_message(data)
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

        # if no payload found
        if not data:
            QMessageBox.information(self, "Extracted message", "No embedded message found.")
            return
        self._show_extracted_message(data)

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
        # extract button state depends on file type and LSB mode
        self._update_extract_button_state()

    def _update_message_metrics(self):
        # skip if no file is loaded yet
        if self.cached_capacity is None:
            self.msg_size_label.setText("Message size: 0 bytes")
            self.cap_used_label.setText("Capacity used: N/A")
            return
        # estimate byte size without encoding (use character count * 4 as worst case for UTF-8)
        # this avoids the expensive encode() operation for large texts
        text = self.msg_edit.toPlainText()
        char_count = len(text)
        # rough estimate: UTF-8 is 1-4 bytes per character; use 1.2x as reasonable approximation
        estimated_size = int(char_count * 1.2)
        self.msg_size_label.setText(f"Message size: ~{estimated_size} bytes")
        # use cached capacity to avoid recalculating on every keystroke
        cap_bytes = self.cached_capacity
        if cap_bytes == -1:
            # unlimited capacity (append mode)
            self.cap_used_label.setText("Capacity used: (unlimited)")
        elif cap_bytes and cap_bytes > 0:
            pct = estimated_size * 100 / cap_bytes
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