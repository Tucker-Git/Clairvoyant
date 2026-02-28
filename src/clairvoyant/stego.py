from PIL import Image
import cv2
import os
import shutil
import tempfile
import subprocess
import glob
import sys

HEADER_LEN_BYTES = 4


def _find_ffmpeg() -> str:
    """Locate an ffmpeg binary.

    Priority:
    1. Bundled binary under `assets/ffmpeg/<platform>/ffmpeg` (or .exe)
    2. `sys._MEIPASS` when running from a PyInstaller bundle
    3. `ffmpeg` on PATH via `shutil.which`

    Ensures the binary is executable on POSIX by setting mode to 755.
    Returns the path to the ffmpeg binary or `None` if not found.
    """
    plat = 'windows' if sys.platform.startswith('win') else 'macos' if sys.platform == 'darwin' else 'linux'
    exe_name = 'ffmpeg.exe' if plat == 'windows' else 'ffmpeg'

    # candidate in bundle (PyInstaller puts files into _MEIPASS)
    base_candidates = []
    if getattr(sys, '_MEIPASS', None):
        base_candidates.append(sys._MEIPASS)
    # repository relative path (two levels up from package file)
    pkg_root = os.path.abspath(os.path.join(os.path.dirname(__file__), '..', '..'))
    base_candidates.append(pkg_root)

    for base in base_candidates:
        candidate = os.path.join(base, 'assets', 'ffmpeg', plat, exe_name)
        if os.path.exists(candidate):
            try:
                if not sys.platform.startswith('win'):
                    os.chmod(candidate, 0o755)
                return candidate
            except Exception:
                return candidate

    # fallback to PATH
    path = shutil.which('ffmpeg')
    if path and not sys.platform.startswith('win'):
        try:
            os.chmod(path, 0o755)
        except Exception:
            pass
    return path


def _bytes_to_bits(data: bytes):
    for byte in data:
        for i in range(7, -1, -1):
            yield (byte >> i) & 1


def _bits_to_bytes(bits):
    b = bytearray()
    acc = 0
    count = 0
    for bit in bits:
        acc = (acc << 1) | (bit & 1)
        count += 1
        if count == 8:
            b.append(acc)
            acc = 0
            count = 0
    return bytes(b)


def estimate_image_capacity(image_path: str) -> int:
    """Return capacity in bytes available for embedding (using 1 LSB per color byte)."""
    img = Image.open(image_path).convert("RGB")
    w, h = img.size
    total_bits = w * h * 3
    usable_bits = total_bits - (HEADER_LEN_BYTES * 8)
    if usable_bits < 0:
        return 0
    return usable_bits // 8


def estimate_video_capacity(video_path: str) -> int:
    """Estimate capacity (bytes) for a video by counting frames * pixels * 3 / 8."""
    # for appended-payload video stego we don't rely on frame LSBs.
    # report a conservative capacity based on file size (so UI shows reasonable numbers).
    try:
        size = os.path.getsize(video_path)
    except Exception:
        return 0
    # reserve small header/footer space
    if size <= 1024:
        return 0
    return max(0, size - 1024)


def embed_message_into_image(input_path: str, output_path: str, message: bytes):
    img = Image.open(input_path).convert("RGB")
    w, h = img.size
    pixel_bytes = bytearray(img.tobytes())

    length = len(message)
    payload = length.to_bytes(HEADER_LEN_BYTES, "big") + message
    payload_bits = list(_bytes_to_bits(payload))

    if len(payload_bits) > len(pixel_bytes):
        raise ValueError("Payload too large to embed in image")

    for i, bit in enumerate(payload_bits):
        pixel_bytes[i] = (pixel_bytes[i] & 0xFE) | bit

    out = Image.frombytes("RGB", (w, h), bytes(pixel_bytes))
    out.save(output_path)


def extract_message_from_image(input_path: str) -> bytes:
    img = Image.open(input_path).convert("RGB")
    pixel_bytes = bytearray(img.tobytes())

    header_bits = [(pixel_bytes[i] & 1) for i in range(HEADER_LEN_BYTES * 8)]
    header = _bits_to_bytes(header_bits)
    length = int.from_bytes(header, "big")

    total_bits_needed = length * 8
    bits = [(pixel_bytes[HEADER_LEN_BYTES * 8 + i] & 1) for i in range(total_bits_needed)]
    return _bits_to_bytes(bits)


def embed_message_into_video(input_path: str, output_path: str, message: bytes):
    # append the payload to the copied video file's end.
    if not os.path.exists(input_path):
        raise ValueError("Input video file does not exist")
    marker = b'CLRV1'
    length = len(message)
    envelope = marker + length.to_bytes(HEADER_LEN_BYTES, 'big') + message
    # copy file and append envelope
    shutil.copyfile(input_path, output_path)
    with open(output_path, 'ab') as f:
        f.write(envelope)


def extract_message_from_video(input_path: str) -> bytes:
    # Read appended envelope from end of file. This is robust to compression.
    if not os.path.exists(input_path):
        raise ValueError("Input video file does not exist")
    marker = b'CLRV1'
    marker_len = len(marker)
    # read last chunk (up to 10MB) where envelope should be
    max_tail = 10 * 1024 * 1024
    fsize = os.path.getsize(input_path)
    read_len = min(fsize, max_tail)
    with open(input_path, 'rb') as f:
        f.seek(fsize - read_len)
        tail = f.read(read_len)
    # search for marker from the end
    idx = tail.rfind(marker)
    if idx == -1:
        return b""
    # ensure header + length present
    start = idx + marker_len
    if start + HEADER_LEN_BYTES > len(tail):
        return b""
    length = int.from_bytes(tail[start:start + HEADER_LEN_BYTES], 'big')
    payload_start = start + HEADER_LEN_BYTES
    payload_end = payload_start + length
    if payload_end > len(tail):
        # message too large for the read tail; try reading more of the file
        with open(input_path, 'rb') as f:
            f.seek(fsize - read_len + idx + marker_len + HEADER_LEN_BYTES)
            data = f.read(length)
            if len(data) != length:
                return b""
            return data
    return tail[payload_start:payload_end]


def estimate_video_capacity_lsb(video_path: str, bits_per_channel: int = 1) -> int:
    """Estimate capacity (bytes) for LSB-in-frame stego.

    WARNING: This estimate is only meaningful when the output is written
    with a lossless (or near-lossless) codec. LSB changes will be destroyed
    by lossy re-encoding.
    """
    cap = cv2.VideoCapture(video_path)
    if not cap.isOpened():
        return 0
    try:
        frames = int(cap.get(cv2.CAP_PROP_FRAME_COUNT)) or 0
        w = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH))
        h = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT))
        channels = 3
        total_bits = frames * w * h * channels * bits_per_channel
        usable_bits = total_bits - (HEADER_LEN_BYTES * 8)
        if usable_bits < 0:
            return 0
        return usable_bits // 8
    finally:
        cap.release()


def embed_message_into_video_lsb(input_path: str, output_path: str, message: bytes, bits_per_channel: int = 1):
    """Embed a payload into video frames by modifying LSBs of pixel bytes.

    This function prefers an ffmpeg-based frame workflow: extract frames as
    PNG images, modify per-frame LSBs losslessly, then reassemble with a
    lossless codec (FFV1). If `ffmpeg` is not available, it falls back to a
    VideoWriter-based approach (which may fail depending on installed codecs).
    """
    ffmpeg = _find_ffmpeg()
    if ffmpeg:
        # capacity check
        cap_bytes = estimate_video_capacity_lsb(input_path, bits_per_channel=bits_per_channel)
        if cap_bytes and len(message) > cap_bytes:
            raise ValueError('Payload too large for LSB embedding in this video')

        with tempfile.TemporaryDirectory() as td:
            frame_pattern = os.path.join(td, 'frame_%06d.png')
            # extract frames as PNGs (lossless)
            cmd = [ffmpeg, '-y', '-i', input_path, '-vsync', '0', frame_pattern]
            subprocess.run(cmd, check=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE)

            # read fps for reassembly
            cap = cv2.VideoCapture(input_path)
            fps = cap.get(cv2.CAP_PROP_FPS) or 25.0
            cap.release()

            # collect frame files in sorted order
            frames = sorted(glob.glob(os.path.join(td, 'frame_*.png')))
            if not frames:
                raise RuntimeError('No frames extracted; ffmpeg failed?')

            length = len(message)
            payload = length.to_bytes(HEADER_LEN_BYTES, 'big') + message
            payload_bits = list(_bytes_to_bits(payload))
            total_payload_bits = len(payload_bits)
            bit_idx = 0

            for fp in frames:
                if bit_idx >= total_payload_bits:
                    break
                img = Image.open(fp).convert('RGB')
                w, h = img.size
                pixel_bytes = bytearray(img.tobytes())
                max_modify = min(len(pixel_bytes), total_payload_bits - bit_idx)
                for i in range(max_modify):
                    pixel_bytes[i] = (pixel_bytes[i] & 0xFE) | payload_bits[bit_idx]
                    bit_idx += 1
                out_img = Image.frombytes('RGB', (w, h), bytes(pixel_bytes))
                out_img.save(fp, 'PNG')

            if bit_idx < total_payload_bits:
                raise ValueError('Not enough capacity in frames to embed payload')

            # reassemble frames into lossless video (ffv1) and copy audio if present
            cmd = [
                ffmpeg, '-y', '-framerate', str(round(fps, 3)), '-i', os.path.join(td, 'frame_%06d.png'),
                '-i', input_path, '-map', '0:v', '-map', '1:a?', '-c:v', 'ffv1', '-c:a', 'copy', output_path
            ]
            subprocess.run(cmd, check=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
            return

    # fallback: try in-memory VideoWriter approach (may fail depending on codecs)
    cap = cv2.VideoCapture(input_path)
    if not cap.isOpened():
        raise ValueError("Input video file does not exist or cannot be opened")

    frames = int(cap.get(cv2.CAP_PROP_FRAME_COUNT)) or None
    fps = cap.get(cv2.CAP_PROP_FPS) or 25.0
    w = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH))
    h = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT))

    # try to reuse input fourcc if possible
    fourcc_int = int(cap.get(cv2.CAP_PROP_FOURCC))
    try:
        fourcc_guess = "".join([chr((fourcc_int >> (8 * i)) & 0xFF) for i in range(4)])
    except Exception:
        fourcc_guess = ''

    def _open_writer(codecs_try):
        for c in codecs_try:
            writer = cv2.VideoWriter(output_path, cv2.VideoWriter_fourcc(*c), fps, (w, h))
            if writer.isOpened():
                return writer, c
        return None, None

    preferred = []
    if fourcc_guess and fourcc_guess.strip():
        preferred.append(fourcc_guess)
    preferred.extend(['FFV1', 'MJPG', 'XVID', 'mp4v'])

    out, used = _open_writer(preferred)
    if out is None:
        cap.release()
        raise RuntimeError('Failed to open VideoWriter for output; cannot perform LSB embedding')

    length = len(message)
    payload = length.to_bytes(HEADER_LEN_BYTES, 'big') + message
    payload_bits = list(_bytes_to_bits(payload))
    total_payload_bits = len(payload_bits)
    bit_idx = 0

    idx = 0
    while True:
        ret, frame = cap.read()
        if not ret:
            break
        if bit_idx < total_payload_bits:
            flat = frame.flatten()
            max_modify = min(len(flat), total_payload_bits - bit_idx)
            for i in range(max_modify):
                flat[i] = (int(flat[i]) & 0xFE) | payload_bits[bit_idx]
                bit_idx += 1
            frame = flat.reshape(frame.shape)
        out.write(frame)
        idx += 1

    cap.release()
    out.release()


def extract_message_from_video_lsb(input_path: str) -> bytes:
    """Extract a message embedded using `embed_message_into_video_lsb`.

    Returns empty bytes if extraction fails or no valid header found.
    """
    ffmpeg = _find_ffmpeg()
    if ffmpeg:
        with tempfile.TemporaryDirectory() as td:
            frame_pattern = os.path.join(td, 'frame_%06d.png')
            cmd = [ffmpeg, '-y', '-i', input_path, '-vsync', '0', frame_pattern]
            subprocess.run(cmd, check=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
            frames = sorted(glob.glob(os.path.join(td, 'frame_*.png')))
            if not frames:
                return b''
            header_bits = []
            payload_bits = []
            header_bits_needed = HEADER_LEN_BYTES * 8
            length = None
            total_payload_bits = None
            for fp in frames:
                img = Image.open(fp).convert('RGB')
                flat = bytearray(img.tobytes())
                for byte in flat:
                    bit = int(byte) & 1
                    if len(header_bits) < header_bits_needed:
                        header_bits.append(bit)
                        if len(header_bits) == header_bits_needed:
                            header = _bits_to_bytes(header_bits)
                            length = int.from_bytes(header, 'big')
                            total_payload_bits = length * 8
                            if total_payload_bits == 0:
                                return b''
                    else:
                        if len(payload_bits) < total_payload_bits:
                            payload_bits.append(bit)
                        if total_payload_bits is not None and len(payload_bits) >= total_payload_bits:
                            return _bits_to_bytes(payload_bits)
            return b''

    cap = cv2.VideoCapture(input_path)
    if not cap.isOpened():
        raise ValueError("Input video file does not exist or cannot be opened")

    header_bits = []
    payload_bits = []
    header_bits_needed = HEADER_LEN_BYTES * 8
    length = None
    total_payload_bits = None

    try:
        while True:
            ret, frame = cap.read()
            if not ret:
                break
            flat = frame.flatten()
            for b in flat:
                bit = int(b) & 1
                if len(header_bits) < header_bits_needed:
                    header_bits.append(bit)
                    if len(header_bits) == header_bits_needed:
                        header = _bits_to_bytes(header_bits)
                        length = int.from_bytes(header, 'big')
                        total_payload_bits = length * 8
                        if total_payload_bits == 0:
                            return b''
                else:
                    if len(payload_bits) < total_payload_bits:
                        payload_bits.append(bit)
                    if total_payload_bits is not None and len(payload_bits) >= total_payload_bits:
                        return _bits_to_bytes(payload_bits)
        return b''
    finally:
        cap.release()
