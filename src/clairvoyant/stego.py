from PIL import Image
import cv2
import os
import shutil
import tempfile
import subprocess
import glob
import sys

HEADER_LEN_BYTES = 4


def _get_platform() -> str:
    # detect platform ('windows', 'macos', or 'linux')
    if sys.platform.startswith('win'):
        return 'windows'
    elif sys.platform == 'darwin':
        return 'macos'
    else:
        return 'linux'


def _find_ffmpeg() -> str:
    # find ffmpeg binary (bundle → PyInstaller → PATH)
    platform = _get_platform()
    exe_name = 'ffmpeg.exe' if platform == 'windows' else 'ffmpeg'

    # check for built-in ffmpeg (/assets/ffmpeg/<platform>)
    base_candidates = []
    if getattr(sys, '_MEIPASS', None):
        base_candidates.append(sys._MEIPASS)
    # check package root directory
    pkg_root = os.path.abspath(os.path.join(os.path.dirname(__file__), '..', '..'))
    base_candidates.append(pkg_root)

    for base in base_candidates:
        candidate = os.path.join(base, 'assets', 'ffmpeg', platform, exe_name)
        if os.path.exists(candidate):
            try:
                if not sys.platform.startswith('win'):
                    os.chmod(candidate, 0o755)
                return candidate
            except Exception:
                return candidate

    # fallback: try system PATH
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


def _extract_lsb_bits(byte_arrays):
    # extract lsb bits from byte arrays (generator)
    for byte_array in byte_arrays:
        for byte_val in byte_array:
            yield int(byte_val) & 1


def estimate_image_capacity(image_path: str) -> int:
    # estimate capacity in bytes for image lsb embedding
    img = Image.open(image_path).convert("RGB")
    w, h = img.size
    total_bits = w * h * 3
    usable_bits = total_bits - (HEADER_LEN_BYTES * 8)
    if usable_bits < 0:
        return 0
    return usable_bits // 8


def estimate_video_capacity(video_path: str) -> int:
    # estimate capacity for append-mode video stego (-1 = unlimited)
    try:
        if not os.path.exists(video_path):
            return 0
        # sentinel value: unlimited capacity for append mode
        return -1
    except Exception:
        return 0


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
    # append payload to end of video file (stays playable)
    if not os.path.exists(input_path):
        raise ValueError("Input video file does not exist")
    marker = b'CLRV1'
    length = len(message)
    envelope = marker + length.to_bytes(HEADER_LEN_BYTES, 'big') + message
    # copy file then append envelope to end
    shutil.copyfile(input_path, output_path)
    with open(output_path, 'ab') as f:
        f.write(envelope)


def extract_message_from_video(input_path: str) -> bytes:
    # read envelope appended to end of file (robust to compression)
    if not os.path.exists(input_path):
        raise ValueError("Input video file does not exist")
    marker = b'CLRV1'
    marker_len = len(marker)
    # read last 10MB chunk (where envelope should be)
    max_tail = 10 * 1024 * 1024
    fsize = os.path.getsize(input_path)
    read_len = min(fsize, max_tail)
    with open(input_path, 'rb') as f:
        f.seek(fsize - read_len)
        tail = f.read(read_len)
    # search for marker from end
    idx = tail.rfind(marker)
    if idx == -1:
        return b""
    # verify header + length present
    start = idx + marker_len
    if start + HEADER_LEN_BYTES > len(tail):
        return b""
    length = int.from_bytes(tail[start:start + HEADER_LEN_BYTES], 'big')
    payload_start = start + HEADER_LEN_BYTES
    payload_end = payload_start + length
    if payload_end > len(tail):
        # payload larger than tail buffer; seek to exact position and read
        with open(input_path, 'rb') as f:
            f.seek(fsize - read_len + idx + marker_len + HEADER_LEN_BYTES)
            data = f.read(length)
            if len(data) != length:
                return b""
            return data
    return tail[payload_start:payload_end]


def estimate_video_capacity_lsb(video_path: str, bits_per_channel: int = 1) -> int:
    # estimate capacity for lsb-in-frame stego (lossless codec only)
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
    # embed message in video frame lsb (ffmpeg preferred, cv2 fallback)
    ffmpeg = _find_ffmpeg()
    if ffmpeg:
        # capacity check
        cap_bytes = estimate_video_capacity_lsb(input_path, bits_per_channel=bits_per_channel)
        if cap_bytes and len(message) > cap_bytes:
            raise ValueError('payload too large for lsb embedding in this video')

        with tempfile.TemporaryDirectory() as td:
            frame_pattern = os.path.join(td, 'frame_%06d.png')
            # extract frames as PNG (lossless)
            cmd = [ffmpeg, '-y', '-i', input_path, '-vsync', '0', frame_pattern]
            subprocess.run(cmd, check=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE)

            # get fps for reassembly
            cap = cv2.VideoCapture(input_path)
            fps = cap.get(cv2.CAP_PROP_FPS) or 25.0
            cap.release()

            # load frames in order
            frames = sorted(glob.glob(os.path.join(td, 'frame_*.png')))
            if not frames:
                raise RuntimeError('no frames extracted from video')

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
                raise ValueError('insufficient capacity in frames for payload')

            # reassemble with lossless codec (ffv1) and preserve audio
            cmd = [
                ffmpeg, '-y', '-framerate', str(round(fps, 3)), '-i', os.path.join(td, 'frame_%06d.png'),
                '-i', input_path, '-map', '0:v', '-map', '1:a?', '-c:v', 'ffv1', '-c:a', 'copy', output_path
            ]
            subprocess.run(cmd, check=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
            return

    # fallback: cv2 VideoWriter (unreliable with h264 on windows)
    cap = cv2.VideoCapture(input_path)
    if not cap.isOpened():
        raise ValueError("cannot open input video")

    frames = int(cap.get(cv2.CAP_PROP_FRAME_COUNT)) or None
    fps = cap.get(cv2.CAP_PROP_FPS) or 25.0
    w = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH))
    h = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT))

    # try to reuse input codec if available
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
        raise RuntimeError(
            'no compatible codec found for video output. '
            'lsb embedding works best with ffmpeg. consider using .mkv format.'
        )

    length = len(message)
    payload = length.to_bytes(HEADER_LEN_BYTES, 'big') + message
    payload_bits = list(_bytes_to_bits(payload))
    total_payload_bits = len(payload_bits)
    bit_idx = 0

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

    cap.release()
    out.release()


def extract_message_from_video_lsb(input_path: str) -> bytes:
    # extract lsb message from video (prefers ffmpeg)
    ffmpeg = _find_ffmpeg()
    if ffmpeg:
        try:
            return _extract_lsb_via_ffmpeg(input_path, ffmpeg)
        except subprocess.CalledProcessError:
            # ffmpeg failed, try cv2 fallback
            pass

    # fallback to cv2 with safeguards
    return _extract_lsb_via_cv2(input_path)


def _extract_lsb_via_ffmpeg(input_path: str, ffmpeg: str) -> bytes:
    # extract lsb bits from video using ffmpeg frame extraction
    with tempfile.TemporaryDirectory() as td:
        frame_pattern = os.path.join(td, 'frame_%06d.png')
        cmd = [ffmpeg, '-y', '-i', input_path, '-vsync', '0', frame_pattern]
        subprocess.run(cmd, check=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE)

        frames = sorted(glob.glob(os.path.join(td, 'frame_*.png')))
        if not frames:
            return b''

        byte_arrays = (bytearray(Image.open(fp).convert('RGB').tobytes()) for fp in frames)
        return _extract_message_from_bits(_extract_lsb_bits(byte_arrays))


def _extract_lsb_via_cv2(input_path: str) -> bytes:
    # extract lsb bits from video using cv2 (fallback, less reliable)
    cap = cv2.VideoCapture(input_path)
    if not cap.isOpened():
        return b''

    # get frame count to prevent infinite loops on bad codecs
    try:
        frame_count = int(cap.get(cv2.CAP_PROP_FRAME_COUNT)) or 0
    except (ValueError, AttributeError):
        frame_count = 0

    if frame_count == 0:
        cap.release()
        return b''

    max_frames_limit = max(frame_count, 10000)  # prevent infinite loops

    def frame_byte_generator():
        # yield frame arrays as flat byte sequences
        frames_read = 0
        try:
            while frames_read < max_frames_limit:
                ret, frame = cap.read()
                if not ret or frame is None or frame.size == 0:
                    break
                frames_read += 1
                yield frame.flatten()
        finally:
            cap.release()

    return _extract_message_from_bits(_extract_lsb_bits(frame_byte_generator()))


def _extract_message_from_bits(bit_generator) -> bytes:
    # extract message from lsb bit sequence (reads header then payload)
    header_bits = []
    payload_bits = []
    header_bits_needed = HEADER_LEN_BYTES * 8
    length = None
    total_payload_bits = None

    for bit in bit_generator:
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
