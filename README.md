# Clairvoyant, your local steganographer

Icons provided by https://icons8.com/

Clairvoyant is a cross-platform desktop steganography tool.

Quickstart

Option A: Install a pre-built EXE (Windows)
- You can download a prebuilt native executable from the project's GitHub Releases instead of creating a virtual environment and running `main.py`. 
- Releases (intend to) include a single-file Windows EXE and Linux build produced by the repository CI. Automatic releases are on hold, but a pre-release RC version of the Windows build is available now.
- After downloading the Windows EXE, double-click to run it. For Linux mark it executable: `chmod +x Clairvoyant` and run `./Clairvoyant`.

Option B: Create a virtual environment and run the program manually

- NOTE: It may be necessary to install a version of OpenH264 on your machine to take advantage of the experimental LSB mode for encoding payloads into video files.

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

Features
- Image steganography: embed/extract using 1 LSB per color byte for PNG/BMP.
- Video steganography: a robust append/read method that appends an envelope to the video file (marker + length + payload). This avoids lossy re-encoding and survives common containers.
- Optional payload encryption using AES-GCM with a PBKDF2-derived key (passphrase).

Notes & limitations
- Default video method: this method appends the payload to the file (marker + length + payload). This is resilient to compression but means the payload embedded file will grow by the payload size.
- Experimental LSB mode: an LSB-in-frame video mode is toggleable(`src/clairvoyant/stego.py`). This attempts to hide bits in the per-frame pixel LSBs but is fragile: it only survives when the output uses a lossless codec and will be destroyed by lossy re-encoding or container conversions. Use the LSB mode only for lossless workflows and with backups of original files. When `ffmpeg` is available the app will automatically re-encode to lossless frames for LSB operations to improve reliability.
- NOTE: LSB encoding will not work with all video formats. If you encounter an error during encoding, try changing the extension to one that works consistently, like .mkv
- Capacity estimates are conservative (file-size based for video) and are shown as an estimate only.
- No code signing or native installers are included. Use with care and keep backups of original media.