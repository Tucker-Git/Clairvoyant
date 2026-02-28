# Clairvoyant

Clairvoyant is a cross-platform desktop steganography tool (Windows/Linux).

Quickstart

1. Create and activate a virtual environment, then install dependencies:

```bash
python -m venv .venv
.venv\Scripts\activate     # Windows
# or: 
source .venv/bin/activate  # Linux
pip install -r requirements.txt
```

2. Run the GUI:

```bash
python main.py
```

Alternative: download a prebuilt executable
- You can download a prebuilt native executable from the project's GitHub Releases instead of creating a virtual environment and running `main.py`. Releases include a single-file Windows EXE and Linux build produced by the repository CI.
- After downloading the Windows EXE double-click to run it. For Linux mark it executable: `chmod +x Clairvoyant` and run `./Clairvoyant`.


Features
- Image steganography: embed/extract using 1 LSB per color byte for PNG/BMP.
- Video steganography: a robust append/read method that appends an envelope to the video file (marker + length + payload). This avoids lossy re-encoding and survives common containers.
- Optional payload encryption using AES-GCM with a PBKDF2-derived key (passphrase).
- PySide6 GUI with: select file, embed/extract flows, capacity estimate (conservative file-size based for videos), passphrase toggle, and selectable extracted-text dialog for easy copying.
- Application icon support: place `assets/icon.ico` or `assets/icon.png` and the app will load it at startup.

Notes & limitations
- Default video method: the appends the payload to the file (marker + length + payload). This is resilient to compression but means the stego file will grow by the payload size.
- Experimental LSB mode: an LSB-in-frame video mode has been added (`src/clairvoyant/stego.py`). This attempts to hide bits in the per-frame pixel LSBs but is fragile: it only survives when the output uses a lossless codec and will be destroyed by lossy re-encoding or container conversions. Use the LSB mode only for lossless workflows and with backups of original files. When `ffmpeg` is available the app will automatically re-encode to lossless frames for LSB operations to improve reliability.
- Capacity estimates are conservative (file-size based for video) and are shown for guidance only.
- No code signing or native installers are included. Use with care and keep backups of original media.