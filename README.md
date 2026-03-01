# Clairvoyant

> A cross-platform desktop steganography tool for embedding and extracting AES encrypted payloads within images and videos.

Icons provided by [Icons8](https://icons8.com/)

---

## Quickstart

### Option A: Download a pre-built executable (recommended)

Pre-built binaries are available on the [Releases](../../releases) page.

**Windows:** Download `Clairvoyant-Windows-<version>.exe` and double-click to run.

**Ubuntu:** Download `Clairvoyant-Ubuntu-<version>` and run it:
```bash
./Clairvoyant-Ubuntu-<version>
```
> If you get a permission denied error, mark it executable first: `chmod +x Clairvoyant-Ubuntu-<version>`

---

### Option B: Run from source

> To use the experimental LSB video mode you may need to install OpenH264 on your system.

1. Create and activate a virtual environment, then install dependencies:
```bash
python -m venv .venv
.venv\Scripts\activate      # Windows
source .venv/bin/activate   # Linux
pip install -r requirements.txt
```

2. Run the app:
```bash
python main.py
```

---

## Features

**Image steganography** — embed and extract payloads using 1 LSB per color channel byte, supporting PNG and BMP formats.

**Video steganography (default)** — appends a structured envelope (marker + length + payload) directly to the video file. This avoids lossy re-encoding and is resilient to container differences, at the cost of increasing the output file size by the size of the payload.

**Video steganography (experimental LSB mode)** — hides payload bits in per-frame pixel LSBs. This mode is fragile and only survives lossless codecs — lossy re-encoding or container conversion will destroy the payload. When FFmpeg is available, the app will automatically re-encode to lossless frames to improve reliability. Use only in lossless workflows and keep backups of your originals. If you encounter errors, try `.mkv` as your output format.

**Payload encryption** — optionally encrypt your payload with AES-GCM using a PBKDF2-derived key (passphrase) before embedding.

---

## Limitations

- Capacity estimates for video are file-size based and should be treated as approximations only.
- No code signing or native installers are included. Keep backups of original media files before embedding.