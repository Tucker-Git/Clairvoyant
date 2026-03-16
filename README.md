# Clairvoyant

<div align="center">
  <img src="assets/icon.png" width="128" height="128" alt="Clairvoyant icon" />
</div>

> Hide and extract text within images and videos.

Icons provided by [Icons8](https://icons8.com/)

---

## Getting Started

### Download & Run (recommended)

1. Download the latest version from [Releases](../../releases)
2. **Windows:** Double-click `Clairvoyant-<version>.exe`
3. **Linux:** Run `./Clairvoyant-<version>` (may need `chmod +x` first)

### Run from Source

```bash
python -m venv .venv
.venv\Scripts\activate      # Windows
source .venv/bin/activate   # Linux
pip install -r requirements.txt
python main.py
```

---

## How It Works

**For Images:** Messages are hidden in PNG or BMP files using invisible pixel-level encoding.

**For Videos:** Messages are appended to MP4, MKV, MOV, or AVI files. The file stays completely playable while hiding your message inside. For best results with LSB mode, use MKV format.

**Optional Encryption:** Protect your message with a passphrase using AES-GCM encryption.

**Large Messages:** Use the built-in file loader to embed messages from text files—no more pasting limits.

---

## Tips

- Always keep backups of original files before embedding
- Save video files with LSB embedded payloads as .mkv, .mp4 will have issues upon extract
- Messages embedded in images will increase file size slightly (this is normal)
- Pasting large amounts of data will cause the application to hang, recommended to utilize .txt file input