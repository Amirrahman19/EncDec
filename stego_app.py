"""Stego Toolkit — combined encoder + decoder GUI (packaged as StegoTool.exe).

One app, two top-level tabs (Encode / Decode), five tools each:
  - Message <-> Image
  - Message <-> Audio (WAV)
  - Image   <-> Audio (WAV)
  - Message <-> Video
  - Image   <-> Video

Self-contained: no dependency on the sibling tool folders, so it can be
frozen into a single portable executable with PyInstaller.

Shows a progress bar and logs every step to the GUI console pane, and also
appends the same log lines to stego_tool.log next to the executable (built
--windowed, so no terminal window pops up).
"""

import base64
import io
import os
import sys
import queue
import subprocess
import tempfile
import threading
import time
import wave

import numpy as np
import cv2
import imageio_ffmpeg
from PIL import Image
from cryptography.exceptions import InvalidTag
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from cryptography.hazmat.primitives.kdf.pbkdf2 import PBKDF2HMAC

import tkinter as tk
from tkinter import ttk, filedialog, messagebox

HEADER_BITS = 32

if getattr(sys, "frozen", False):
    _LOG_DIR = os.path.dirname(sys.executable)
    _ASSET_DIR = sys._MEIPASS
else:
    _LOG_DIR = os.path.dirname(os.path.abspath(__file__))
    _ASSET_DIR = os.path.join(_LOG_DIR, "assets")
_LOG_FILE_PATH = os.path.join(_LOG_DIR, "stego_tool.log")
_ICON_PATH = os.path.join(_ASSET_DIR, "icon.ico")


def _append_log_file(line: str) -> None:
    try:
        with open(_LOG_FILE_PATH, "a", encoding="utf-8") as f:
            f.write(line + "\n")
    except OSError:
        pass


# ==========================================================================
# Shared bit-packing helpers
# ==========================================================================

def _bytes_to_bits(data: bytes):
    return np.unpackbits(np.frombuffer(data, dtype=np.uint8))


def _bits_to_bytes(bits):
    return np.packbits(np.asarray(bits, dtype=np.uint8)).tobytes()


# ==========================================================================
# Optional password encryption (AES-256-GCM, PBKDF2-HMAC-SHA256)
# Blob layout: b"SGE1" | salt(16) | nonce(12) | ciphertext+tag
# Same format as the phone web app, so both interoperate.
# ==========================================================================

MAGIC = b"SGE1"
KDF_ITERATIONS = 200_000


class WrongPasswordError(ValueError):
    pass


def _derive_key(password: str, salt: bytes) -> bytes:
    return PBKDF2HMAC(algorithm=hashes.SHA256(), length=32, salt=salt,
                      iterations=KDF_ITERATIONS).derive(password.encode("utf-8"))


def encrypt_bytes(data: bytes, password: str) -> bytes:
    salt, nonce = os.urandom(16), os.urandom(12)
    return MAGIC + salt + nonce + AESGCM(_derive_key(password, salt)).encrypt(nonce, data, MAGIC)


def decrypt_bytes(blob: bytes, password: str) -> bytes:
    if len(blob) < len(MAGIC) + 16 + 12 + 16:
        raise ValueError("Encrypted data is truncated.")
    salt, nonce, ct = blob[4:20], blob[20:32], blob[32:]
    try:
        return AESGCM(_derive_key(password, salt)).decrypt(nonce, ct, MAGIC)
    except InvalidTag:
        raise WrongPasswordError("Wrong password, or the data was altered/corrupted.") from None


def _seal(data: bytes, password: str) -> bytes:
    return encrypt_bytes(data, password) if password else data


def _open_payload(data: bytes, password: str) -> bytes:
    if data.startswith(MAGIC):
        if not password:
            raise WrongPasswordError("This content is password-protected. Enter the password.")
        return decrypt_bytes(data, password)
    return data


def _open_text(data: bytes, password: str) -> str:
    data = _open_payload(data, password)
    try:
        return data.decode("utf-8")
    except UnicodeDecodeError:
        raise ValueError("No readable hidden message found in this file.") from None


def encrypt_text(message: str, password: str) -> str:
    if not password:
        raise ValueError("A password is required for text encryption.")
    return base64.b64encode(encrypt_bytes(message.encode("utf-8"), password)).decode("ascii")


def decrypt_text(token: str, password: str) -> str:
    if not password:
        raise ValueError("A password is required to decrypt.")
    try:
        blob = base64.b64decode("".join(token.split()), validate=True)
    except (ValueError, base64.binascii.Error):
        raise ValueError("That doesn't look like an encrypted message (bad base64).") from None
    if not blob.startswith(MAGIC):
        raise ValueError("That doesn't look like an encrypted message from this tool.")
    return decrypt_bytes(blob, password).decode("utf-8")


def _pack_payload(data: bytes) -> bytes:
    return len(data).to_bytes(4, "big") + data


def _unpack_length(header_bytes: bytes) -> int:
    return int.from_bytes(header_bytes[:4], "big")


def _embed_bits(flat: np.ndarray, bits: list, progress_cb, stage_start: float, stage_span: float) -> None:
    n = len(bits)
    flat[:n] = (flat[:n] & 0xFE) | bits.astype(flat.dtype)
    if progress_cb:
        progress_cb(stage_start + stage_span, None)


def _ensure_png(path: str) -> str:
    """Force a .png extension. Any other extension (e.g. reusing the source
    .jpg path) would make PIL save as a lossy format, silently destroying
    the embedded LSBs even though the encode step reports success."""
    root, ext = os.path.splitext(path)
    if ext.lower() != ".png":
        return root + ".png"
    return path


def _ensure_avi(path: str) -> str:
    if not path.lower().endswith(".avi"):
        return (path.rsplit(".", 1)[0] if "." in os.path.basename(path) else path) + ".avi"
    return path


def _ensure_wav_ext(path: str) -> str:
    root, ext = os.path.splitext(path)
    if ext.lower() != ".wav":
        return root + ".wav"
    return path


def _run_ffmpeg(args, log=print):
    ffmpeg_exe = imageio_ffmpeg.get_ffmpeg_exe()
    cmd = [ffmpeg_exe] + args
    startupinfo = None
    creationflags = 0
    if os.name == "nt":
        startupinfo = subprocess.STARTUPINFO()
        startupinfo.dwFlags |= subprocess.STARTF_USESHOWWINDOW
        creationflags = subprocess.CREATE_NO_WINDOW
    proc = subprocess.run(
        cmd, capture_output=True, text=True,
        startupinfo=startupinfo, creationflags=creationflags,
    )
    if proc.returncode != 0:
        tail = proc.stderr.strip().splitlines()[-5:] if proc.stderr else []
        raise RuntimeError("ffmpeg conversion failed:\n" + "\n".join(tail))
    return proc


def _ensure_wav_input(input_path, log=print):
    """Any non-WAV (or unreadable) audio file is auto-converted to 16-bit
    PCM WAV via bundled ffmpeg."""
    try:
        with wave.open(input_path, "rb") as wf:
            if wf.getsampwidth() in (1, 2, 4):
                return input_path
        log("WAV uses an unsupported sample width (e.g. 24-bit); converting via ffmpeg...")
    except (wave.Error, EOFError, OSError):
        pass
    log(f"Source audio is not readable as WAV ({os.path.splitext(input_path)[1]}); auto-converting via ffmpeg...")
    fd, temp_wav = tempfile.mkstemp(suffix=".wav")
    os.close(fd)
    _run_ffmpeg(["-y", "-i", input_path, "-ac", "1", "-c:a", "pcm_s16le", temp_wav], log=log)
    log(f"Converted to temporary WAV: {temp_wav}")
    return temp_wav


def _ensure_readable_video(input_path, log=print):
    """If OpenCV can't open the video directly, transcode it to a temp
    lossless AVI (FFV1) via bundled ffmpeg first, then retry."""
    cap = cv2.VideoCapture(input_path)
    opened = cap.isOpened()
    cap.release()
    if opened:
        return input_path
    log(f"OpenCV could not open video directly ({os.path.splitext(input_path)[1]}); "
        f"auto-transcoding via ffmpeg...")
    fd, temp_avi = tempfile.mkstemp(suffix=".avi")
    os.close(fd)
    _run_ffmpeg(["-y", "-i", input_path, "-c:v", "ffv1", temp_avi], log=log)
    log(f"Transcoded to temporary AVI: {temp_avi}")
    return temp_avi


def _read_wav(path):
    with wave.open(path, "rb") as wf:
        params = wf.getparams()
        n_frames = wf.getnframes()
        raw = wf.readframes(n_frames)
    dtype = {1: np.uint8, 2: np.int16, 4: np.int32}.get(params.sampwidth)
    if dtype is None:
        raise ValueError(f"Unsupported sample width: {params.sampwidth} bytes")
    samples = np.frombuffer(raw, dtype=dtype).copy()
    return params, samples


def _read_video_frames(path, progress_cb=None, stage_start=0.0, stage_span=0.3, log=print):
    path = _ensure_readable_video(path, log=log)
    cap = cv2.VideoCapture(path)
    if not cap.isOpened():
        raise ValueError(f"Could not open video: {path}")
    fps = cap.get(cv2.CAP_PROP_FPS) or 25.0
    total_frames = cap.get(cv2.CAP_PROP_FRAME_COUNT) or 0
    frames = []
    i = 0
    while True:
        ret, frame = cap.read()
        if not ret:
            break
        frames.append(frame)
        i += 1
        if progress_cb and total_frames > 0:
            progress_cb(stage_start + stage_span * min(i / total_frames, 1.0), None)
    cap.release()
    if not frames:
        raise ValueError("Video contains no readable frames.")
    log(f"Read {len(frames)} frames at {fps:.2f} fps")
    return frames, fps


def _write_video_frames(frames, fps, output_path, progress_cb=None, stage_start=0.7, stage_span=0.3, log=print):
    h, w = frames[0].shape[:2]
    fourcc = cv2.VideoWriter_fourcc(*"FFV1")
    vw = cv2.VideoWriter(output_path, fourcc, fps, (w, h))
    if not vw.isOpened():
        raise RuntimeError("Could not open lossless video writer (FFV1/AVI).")
    total = len(frames)
    for i, frame in enumerate(frames):
        vw.write(frame)
        if progress_cb:
            progress_cb(stage_start + stage_span * ((i + 1) / total), None)
    vw.release()
    log(f"Wrote {total} frames to {output_path}")


# ==========================================================================
# Encode operations
# ==========================================================================

def encode_message_in_image(input_path, message, output_path, progress_cb=None, log=print, password=""):
    log(f"Loading image: {input_path}")
    if progress_cb:
        progress_cb(0.02, "Loading image...")
    img = Image.open(input_path).convert("RGB")
    arr = np.array(img)
    flat = arr.reshape(-1)

    payload = _pack_payload(_seal(message.encode("utf-8"), password))
    bits = _bytes_to_bits(payload)
    log(f"Payload size: {len(payload)} bytes ({len(bits)} bits)")

    capacity = flat.size
    if len(bits) > capacity:
        raise ValueError(
            f"Message too large for this image. Capacity: {capacity // 8} bytes, "
            f"needed: {len(bits) // 8} bytes."
        )

    log("Embedding bits into image LSBs...")
    _embed_bits(flat, bits, progress_cb, 0.1, 0.7)

    output_path = _ensure_png(output_path)
    log(f"Saving output image as lossless PNG: {output_path}")
    if progress_cb:
        progress_cb(0.85, "Saving output image...")
    Image.fromarray(flat.reshape(arr.shape), mode="RGB").save(output_path, format="PNG")
    if progress_cb:
        progress_cb(1.0, "Done.")
    log("Encode complete.")
    return output_path


def encode_message_in_audio(input_path, message, output_path, progress_cb=None, log=print, password=""):
    log(f"Loading audio: {input_path}")
    if progress_cb:
        progress_cb(0.02, "Loading audio...")
    input_path = _ensure_wav_input(input_path, log=log)
    params, samples = _read_wav(input_path)

    payload = _pack_payload(_seal(message.encode("utf-8"), password))
    bits = _bytes_to_bits(payload)
    log(f"Payload size: {len(payload)} bytes ({len(bits)} bits)")

    capacity = samples.size
    if len(bits) > capacity:
        raise ValueError(
            f"Message too large for this audio file. Capacity: {capacity // 8} bytes, "
            f"needed: {len(bits) // 8} bytes."
        )

    log("Embedding bits into audio sample LSBs...")
    original_dtype = samples.dtype
    work = samples.astype(np.int64)
    _embed_bits(work, bits, progress_cb, 0.1, 0.7)
    samples = work.astype(original_dtype)

    output_path = _ensure_wav_ext(output_path)
    log(f"Saving output audio as PCM WAV: {output_path}")
    if progress_cb:
        progress_cb(0.85, "Saving output audio...")
    with wave.open(output_path, "wb") as wf:
        wf.setparams(params)
        wf.writeframes(samples.tobytes())
    if progress_cb:
        progress_cb(1.0, "Done.")
    log("Encode complete.")
    return output_path


def encode_image_in_audio(image_path, audio_path, output_path, progress_cb=None, log=print, password=""):
    log(f"Loading image: {image_path}")
    if progress_cb:
        progress_cb(0.02, "Loading image...")
    img = Image.open(image_path).convert("RGB")
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    image_bytes = buf.getvalue()
    log(f"Encoded image to PNG: {len(image_bytes)} bytes")

    log(f"Loading audio: {audio_path}")
    if progress_cb:
        progress_cb(0.1, "Loading audio...")
    audio_path = _ensure_wav_input(audio_path, log=log)
    params, samples = _read_wav(audio_path)

    payload = _pack_payload(_seal(image_bytes, password))
    bits = _bytes_to_bits(payload)
    log(f"Payload size: {len(payload)} bytes ({len(bits)} bits)")

    capacity = samples.size
    if len(bits) > capacity:
        raise ValueError(
            f"Image too large for this audio file. Capacity: {capacity // 8} bytes, "
            f"needed: {len(bits) // 8} bytes. Try a smaller image or longer audio."
        )

    log("Embedding bits into audio sample LSBs...")
    original_dtype = samples.dtype
    work = samples.astype(np.int64)
    _embed_bits(work, bits, progress_cb, 0.15, 0.65)
    samples = work.astype(original_dtype)

    output_path = _ensure_wav_ext(output_path)
    log(f"Saving output audio as PCM WAV: {output_path}")
    if progress_cb:
        progress_cb(0.85, "Saving output audio...")
    with wave.open(output_path, "wb") as wf:
        wf.setparams(params)
        wf.writeframes(samples.tobytes())
    if progress_cb:
        progress_cb(1.0, "Done.")
    log("Encode complete.")
    return output_path


def encode_message_in_video(input_path, message, output_path, progress_cb=None, log=print, password=""):
    log(f"Loading video: {input_path}")
    frames, fps = _read_video_frames(input_path, progress_cb, 0.0, 0.3, log=log)

    stacked = np.stack(frames)
    flat = stacked.reshape(-1)

    payload = _pack_payload(_seal(message.encode("utf-8"), password))
    bits = _bytes_to_bits(payload)
    log(f"Payload size: {len(payload)} bytes ({len(bits)} bits)")

    capacity = flat.size
    if len(bits) > capacity:
        raise ValueError(
            f"Message too large for this video. Capacity: {capacity // 8} bytes, "
            f"needed: {len(bits) // 8} bytes."
        )

    log("Embedding bits into video frame LSBs...")
    _embed_bits(flat, bits, progress_cb, 0.3, 0.4)

    output_path = _ensure_avi(output_path)
    log(f"Writing lossless FFV1 AVI: {output_path}")
    _write_video_frames(list(stacked), fps, output_path, progress_cb, 0.7, 0.3, log=log)
    if progress_cb:
        progress_cb(1.0, "Done.")
    log("Encode complete.")
    return output_path


def encode_image_in_video(image_path, video_path, output_path, progress_cb=None, log=print, password=""):
    log(f"Loading image: {image_path}")
    img = Image.open(image_path).convert("RGB")
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    image_bytes = buf.getvalue()
    log(f"Encoded image to PNG: {len(image_bytes)} bytes")

    log(f"Loading video: {video_path}")
    frames, fps = _read_video_frames(video_path, progress_cb, 0.0, 0.3, log=log)
    stacked = np.stack(frames)
    flat = stacked.reshape(-1)

    payload = _pack_payload(_seal(image_bytes, password))
    bits = _bytes_to_bits(payload)
    log(f"Payload size: {len(payload)} bytes ({len(bits)} bits)")

    capacity = flat.size
    if len(bits) > capacity:
        raise ValueError(
            f"Image too large for this video. Capacity: {capacity // 8} bytes, "
            f"needed: {len(bits) // 8} bytes. Try a smaller image or longer video."
        )

    log("Embedding bits into video frame LSBs...")
    _embed_bits(flat, bits, progress_cb, 0.3, 0.4)

    output_path = _ensure_avi(output_path)
    log(f"Writing lossless FFV1 AVI: {output_path}")
    _write_video_frames(list(stacked), fps, output_path, progress_cb, 0.7, 0.3, log=log)
    if progress_cb:
        progress_cb(1.0, "Done.")
    log("Encode complete.")
    return output_path


# ==========================================================================
# Decode operations
# ==========================================================================

def decode_message_from_image(input_path, progress_cb=None, log=print, password=""):
    log(f"Loading image: {input_path}")
    if progress_cb:
        progress_cb(0.05, "Loading image...")
    img = Image.open(input_path).convert("RGB")
    arr = np.array(img)
    flat = arr.reshape(-1)

    if progress_cb:
        progress_cb(0.3, "Reading header...")
    header_bits = (flat[:HEADER_BITS] & 1).tolist()
    length = _unpack_length(_bits_to_bytes(header_bits))
    log(f"Header reports payload length: {length} bytes")

    total_bits = HEADER_BITS + length * 8
    if total_bits > flat.size:
        raise ValueError("Image does not contain a valid embedded message.")

    if progress_cb:
        progress_cb(0.6, "Extracting payload...")
    payload_bits = flat[HEADER_BITS:total_bits] & 1
    data = _bits_to_bytes(payload_bits)
    message = _open_text(data, password)
    if progress_cb:
        progress_cb(1.0, "Done.")
    log("Decode complete.")
    return message


def decode_message_from_audio(input_path, progress_cb=None, log=print, password=""):
    log(f"Loading audio: {input_path}")
    if progress_cb:
        progress_cb(0.05, "Loading audio...")
    input_path = _ensure_wav_input(input_path, log=log)
    _, samples = _read_wav(input_path)

    if progress_cb:
        progress_cb(0.3, "Reading header...")
    header_bits = (samples[:HEADER_BITS].astype(np.int64) & 1)
    length = _unpack_length(_bits_to_bytes(header_bits))
    log(f"Header reports payload length: {length} bytes")

    total_bits = HEADER_BITS + length * 8
    if total_bits > samples.size:
        raise ValueError("Audio file does not contain a valid embedded message.")

    if progress_cb:
        progress_cb(0.6, "Extracting payload...")
    payload_bits = (samples[HEADER_BITS:total_bits].astype(np.int64) & 1)
    data = _bits_to_bytes(payload_bits)
    message = _open_text(data, password)
    if progress_cb:
        progress_cb(1.0, "Done.")
    log("Decode complete.")
    return message


def decode_image_from_audio(audio_path, output_image_path, progress_cb=None, log=print, password=""):
    log(f"Loading audio: {audio_path}")
    if progress_cb:
        progress_cb(0.05, "Loading audio...")
    audio_path = _ensure_wav_input(audio_path, log=log)
    _, samples = _read_wav(audio_path)

    if progress_cb:
        progress_cb(0.25, "Reading header...")
    header_bits = (samples[:HEADER_BITS].astype(np.int64) & 1)
    length = _unpack_length(_bits_to_bytes(header_bits))
    log(f"Header reports payload length: {length} bytes")

    total_bits = HEADER_BITS + length * 8
    if total_bits > samples.size:
        raise ValueError("Audio file does not contain a valid embedded image.")

    if progress_cb:
        progress_cb(0.5, "Extracting payload...")
    payload_bits = (samples[HEADER_BITS:total_bits].astype(np.int64) & 1)
    data = _bits_to_bytes(payload_bits)

    if progress_cb:
        progress_cb(0.85, "Decoding image and saving...")
    img = Image.open(io.BytesIO(_open_payload(data, password)))
    img.save(output_image_path)
    if progress_cb:
        progress_cb(1.0, "Done.")
    log(f"Saved extracted image to: {output_image_path}")
    log("Decode complete.")


def decode_message_from_video(input_path, progress_cb=None, log=print, password=""):
    log(f"Loading video: {input_path}")
    frames, _ = _read_video_frames(input_path, progress_cb, 0.0, 0.7, log=log)
    stacked = np.stack(frames)
    flat = stacked.reshape(-1)

    if progress_cb:
        progress_cb(0.75, "Reading header...")
    header_bits = (flat[:HEADER_BITS] & 1).tolist()
    length = _unpack_length(_bits_to_bytes(header_bits))
    log(f"Header reports payload length: {length} bytes")

    total_bits = HEADER_BITS + length * 8
    if total_bits > flat.size:
        raise ValueError("Video does not contain a valid embedded message.")

    if progress_cb:
        progress_cb(0.9, "Extracting payload...")
    payload_bits = flat[HEADER_BITS:total_bits] & 1
    data = _bits_to_bytes(payload_bits)
    message = _open_text(data, password)
    if progress_cb:
        progress_cb(1.0, "Done.")
    log("Decode complete.")
    return message


def decode_image_from_video(video_path, output_image_path, progress_cb=None, log=print, password=""):
    log(f"Loading video: {video_path}")
    frames, _ = _read_video_frames(video_path, progress_cb, 0.0, 0.6, log=log)
    stacked = np.stack(frames)
    flat = stacked.reshape(-1)

    if progress_cb:
        progress_cb(0.65, "Reading header...")
    header_bits = (flat[:HEADER_BITS] & 1).tolist()
    length = _unpack_length(_bits_to_bytes(header_bits))
    log(f"Header reports payload length: {length} bytes")

    total_bits = HEADER_BITS + length * 8
    if total_bits > flat.size:
        raise ValueError("Video does not contain a valid embedded image.")

    if progress_cb:
        progress_cb(0.8, "Extracting payload...")
    payload_bits = flat[HEADER_BITS:total_bits] & 1
    data = _bits_to_bytes(payload_bits)

    if progress_cb:
        progress_cb(0.92, "Decoding image and saving...")
    img = Image.open(io.BytesIO(_open_payload(data, password)))
    img.save(output_image_path)
    if progress_cb:
        progress_cb(1.0, "Done.")
    log(f"Saved extracted image to: {output_image_path}")
    log("Decode complete.")


# ==========================================================================
# Cyber-themed GUI
# ==========================================================================

BG = "#070b10"
PANEL = "#0d1420"
BORDER = "#1c2b3a"
NEON_GREEN = "#39ff6a"
NEON_GREEN_DIM = "#1f8f44"
NEON_CYAN = "#00e5ff"
TEXT = "#d7f7e2"
MUTED = "#5f7a72"
ERR = "#ff4d6d"
FONT_MONO = ("Consolas", 10)
FONT_MONO_BOLD = ("Consolas", 11, "bold")
FONT_TITLE = ("Consolas", 16, "bold")

MODES = [
    "Text <-> Cipher (no file)",
    "Message <-> Image",
    "Message <-> Audio",
    "Image <-> Audio",
    "Message <-> Video",
    "Image <-> Video",
]

IMAGE_TYPES = [("Image files", "*.png *.bmp *.jpg *.jpeg *.gif *.tiff *.webp"), ("All files", "*.*")]
AUDIO_SRC_TYPES = [("Audio files", "*.wav *.mp3 *.m4a *.flac *.ogg *.aac *.wma"), ("All files", "*.*")]
AUDIO_OUT_TYPES = [("WAV files", "*.wav")]
VIDEO_SRC_TYPES = [("Video files", "*.avi *.mp4 *.mov *.mkv *.webm *.flv *.wmv"), ("All files", "*.*")]
VIDEO_OUT_TYPES = [("AVI video", "*.avi")]
PNG_OUT_TYPES = [("PNG image", "*.png")]


def apply_cyber_style(root):
    style = ttk.Style(root)
    try:
        style.theme_use("clam")
    except tk.TclError:
        pass

    root.configure(bg=BG)

    style.configure("TFrame", background=BG)
    style.configure("Panel.TFrame", background=PANEL)
    style.configure("TLabel", background=BG, foreground=TEXT, font=FONT_MONO)
    style.configure("Muted.TLabel", background=BG, foreground=MUTED, font=("Consolas", 9))
    style.configure("Title.TLabel", background=BG, foreground=NEON_GREEN, font=FONT_TITLE)
    style.configure("Sub.TLabel", background=BG, foreground=NEON_CYAN, font=("Consolas", 9))

    style.configure("TEntry", fieldbackground=PANEL, foreground=TEXT, insertcolor=NEON_GREEN,
                     bordercolor=BORDER, lightcolor=BORDER, darkcolor=BORDER)
    style.map("TEntry", fieldbackground=[("readonly", PANEL)])

    style.configure("TCombobox", fieldbackground=PANEL, background=PANEL, foreground=TEXT,
                     arrowcolor=NEON_GREEN, bordercolor=BORDER)
    style.map("TCombobox", fieldbackground=[("readonly", PANEL)], foreground=[("readonly", TEXT)])

    style.configure("Neon.TButton", background=NEON_GREEN_DIM, foreground="#06130a",
                     font=FONT_MONO_BOLD, borderwidth=0, focuscolor=NEON_GREEN)
    style.map("Neon.TButton",
              background=[("active", NEON_GREEN), ("disabled", "#2a3a33")],
              foreground=[("disabled", "#5a6a62")])

    style.configure("Ghost.TButton", background=PANEL, foreground=NEON_CYAN,
                     font=("Consolas", 9), borderwidth=1, bordercolor=BORDER)
    style.map("Ghost.TButton", background=[("active", "#132030")])

    style.configure("Horizontal.TProgressbar", background=NEON_GREEN, troughcolor=PANEL,
                     bordercolor=BORDER, lightcolor=NEON_GREEN, darkcolor=NEON_GREEN)

    style.configure("TNotebook", background=BG, bordercolor=BORDER, tabmargins=[0, 4, 0, 0])
    style.configure("TNotebook.Tab", background=PANEL, foreground=MUTED,
                     font=FONT_MONO_BOLD, padding=[18, 10])
    style.map("TNotebook.Tab",
              background=[("selected", BG)],
              foreground=[("selected", NEON_GREEN)])

    return style


class ToolPanel(ttk.Frame):
    """One Encode or one Decode panel, with its own tool dropdown + fields."""

    def __init__(self, parent, action: str, run_callback, log_callback, progress_callback):
        super().__init__(parent, style="TFrame", padding=16)
        self.action = action  # "encode" | "decode"
        self.run_callback = run_callback
        self.log = log_callback
        self.progress_cb = progress_callback
        self.field_entries = {}
        self.worker_thread = None
        self.result_message_var = None

        top = ttk.Frame(self, style="TFrame")
        top.pack(fill="x")
        ttk.Label(top, text="> SELECT TOOL", style="Sub.TLabel").pack(anchor="w")
        self.mode_var = tk.StringVar(value=MODES[0])
        mode_combo = ttk.Combobox(top, textvariable=self.mode_var, values=MODES, state="readonly", width=34)
        mode_combo.pack(anchor="w", pady=(4, 0))
        mode_combo.bind("<<ComboboxSelected>>", lambda e: self.render_fields())

        self.fields_frame = ttk.Frame(self, style="TFrame")
        self.fields_frame.pack(fill="x", pady=(14, 0))

        pw_row = ttk.Frame(self, style="TFrame")
        pw_row.pack(fill="x", pady=(8, 0))
        ttk.Label(pw_row, text="Password (optional; required\nfor Text <-> Cipher):", style="TLabel").pack(side="left")
        self.password_entry = ttk.Entry(pw_row, width=28, font=FONT_MONO, show="•")
        self.password_entry.pack(side="left", padx=(8, 4))
        self.show_pw = tk.BooleanVar(value=False)
        ttk.Checkbutton(pw_row, text="show", variable=self.show_pw,
                        command=lambda: self.password_entry.config(show="" if self.show_pw.get() else "•")
                        ).pack(side="left")

        btn_text = "⚡ ENCODE" if action == "encode" else "⚡ DECODE"
        self.run_btn = ttk.Button(self, text=btn_text, style="Neon.TButton", command=self.start_run)
        self.run_btn.pack(fill="x", pady=(18, 0), ipady=6)

        progress_frame = ttk.Frame(self, style="TFrame")
        progress_frame.pack(fill="x", pady=(16, 0))
        self.status_var = tk.StringVar(value="IDLE")
        ttk.Label(progress_frame, textvariable=self.status_var, style="Sub.TLabel").pack(anchor="w")
        self.progress = ttk.Progressbar(progress_frame, orient="horizontal", mode="determinate",
                                         maximum=100, style="Horizontal.TProgressbar")
        self.progress.pack(fill="x", pady=(4, 0))

        if True:
            self.result_message_var = tk.StringVar()
            result_frame = ttk.Frame(self, style="TFrame")
            result_frame.pack(fill="x", pady=(16, 0))
            head = ttk.Frame(result_frame, style="TFrame")
            head.pack(fill="x")
            ttk.Label(head, text="> RESULT TEXT (decoded message / cipher text)", style="Sub.TLabel").pack(side="left")
            ttk.Button(head, text="COPY", style="Ghost.TButton", command=self.copy_result).pack(side="right")
            self.result_text = tk.Text(result_frame, width=55, height=4, bg=PANEL, fg=NEON_GREEN,
                                        insertbackground=NEON_GREEN, font=FONT_MONO,
                                        highlightthickness=1, highlightbackground=BORDER, bd=0)
            self.result_text.pack(fill="x", pady=(4, 0))

        self.render_fields()

    def copy_result(self):
        text = self.result_text.get("1.0", tk.END).rstrip("\n")
        if text:
            self.clipboard_clear()
            self.clipboard_append(text)
            self.status_var.set("COPIED TO CLIPBOARD")

    def browse_file(self, entry, filetypes):
        path = filedialog.askopenfilename(filetypes=filetypes)
        if path:
            entry.delete(0, tk.END)
            entry.insert(0, path)

    def browse_save(self, entry, filetypes, default_ext):
        path = filedialog.asksaveasfilename(filetypes=filetypes, defaultextension=default_ext)
        if path:
            entry.delete(0, tk.END)
            entry.insert(0, path)

    def path_row(self, parent, label_text, row, filetypes, save=False, default_ext=""):
        ttk.Label(parent, text=label_text, style="TLabel").grid(row=row, column=0, sticky="w", padx=(0, 8), pady=5)
        entry = ttk.Entry(parent, width=42, font=FONT_MONO)
        entry.grid(row=row, column=1, pady=5, sticky="ew")
        cmd = (lambda: self.browse_save(entry, filetypes, default_ext)) if save else (lambda: self.browse_file(entry, filetypes))
        ttk.Button(parent, text="BROWSE", style="Ghost.TButton", command=cmd).grid(row=row, column=2, padx=(8, 0), pady=5)
        return entry

    def note(self, parent, row, text):
        ttk.Label(parent, text=text, style="Muted.TLabel", wraplength=460, justify="left").grid(
            row=row, column=0, columnspan=3, sticky="w", pady=(6, 0)
        )

    def render_fields(self):
        for widget in self.fields_frame.winfo_children():
            widget.destroy()
        self.fields_frame.columnconfigure(1, weight=1)
        self.field_entries = {}
        mode = self.mode_var.get()
        enc = self.action == "encode"

        if mode == MODES[0]:
            lbl = "Message to encrypt:" if enc else "Cipher text to decrypt:"
            ttk.Label(self.fields_frame, text=lbl, style="TLabel").grid(row=0, column=0, sticky="nw", pady=5)
            text = tk.Text(self.fields_frame, width=42, height=5, bg=PANEL, fg=TEXT,
                            insertbackground=NEON_GREEN, font=FONT_MONO,
                            highlightthickness=1, highlightbackground=BORDER, bd=0)
            text.grid(row=0, column=1, columnspan=2, pady=5, sticky="ew")
            self.field_entries["message"] = text
            self.note(self.fields_frame, 1, "Pure text encryption (AES-256-GCM). Paste the result into any chat app; "
                                            "the other side decrypts with the same password, on desktop or on the phone web app.")

        elif mode == "Message <-> Image":
            label = "Source image:" if enc else "Image with hidden message:"
            self.field_entries["src"] = self.path_row(self.fields_frame, label, 0, IMAGE_TYPES)
            if enc:
                ttk.Label(self.fields_frame, text="Message:", style="TLabel").grid(row=1, column=0, sticky="nw", pady=5)
                text = tk.Text(self.fields_frame, width=42, height=4, bg=PANEL, fg=TEXT,
                                insertbackground=NEON_GREEN, font=FONT_MONO,
                                highlightthickness=1, highlightbackground=BORDER, bd=0)
                text.grid(row=1, column=1, columnspan=2, pady=5, sticky="ew")
                self.field_entries["message"] = text
                self.field_entries["out"] = self.path_row(self.fields_frame, "Output image:", 2, PNG_OUT_TYPES, save=True, default_ext=".png")
                self.note(self.fields_frame, 3, "Output is always lossless PNG — any lossy save would destroy the hidden bits.")

        elif mode == "Message <-> Audio":
            label = "Source audio (any format):" if enc else "Audio with hidden message:"
            self.field_entries["src"] = self.path_row(self.fields_frame, label, 0, AUDIO_SRC_TYPES)
            if enc:
                ttk.Label(self.fields_frame, text="Message:", style="TLabel").grid(row=1, column=0, sticky="nw", pady=5)
                text = tk.Text(self.fields_frame, width=42, height=4, bg=PANEL, fg=TEXT,
                                insertbackground=NEON_GREEN, font=FONT_MONO,
                                highlightthickness=1, highlightbackground=BORDER, bd=0)
                text.grid(row=1, column=1, columnspan=2, pady=5, sticky="ew")
                self.field_entries["message"] = text
                self.field_entries["out"] = self.path_row(self.fields_frame, "Output audio (.wav):", 2, AUDIO_OUT_TYPES, save=True, default_ext=".wav")
                self.note(self.fields_frame, 3, "Non-WAV sources are auto-converted to lossless PCM WAV via bundled ffmpeg.")

        elif mode == "Image <-> Audio":
            if enc:
                self.field_entries["image"] = self.path_row(self.fields_frame, "Image to hide:", 0, IMAGE_TYPES)
                self.field_entries["src"] = self.path_row(self.fields_frame, "Source audio (any format):", 1, AUDIO_SRC_TYPES)
                self.field_entries["out"] = self.path_row(self.fields_frame, "Output audio (.wav):", 2, AUDIO_OUT_TYPES, save=True, default_ext=".wav")
                self.note(self.fields_frame, 3, "Non-WAV sources are auto-converted to lossless PCM WAV via bundled ffmpeg.")
            else:
                self.field_entries["src"] = self.path_row(self.fields_frame, "Audio with hidden image:", 0, AUDIO_SRC_TYPES)
                self.field_entries["out"] = self.path_row(self.fields_frame, "Save extracted image as:", 1, PNG_OUT_TYPES, save=True, default_ext=".png")

        elif mode == "Message <-> Video":
            label = "Source video (any format):" if enc else "Video with hidden message:"
            self.field_entries["src"] = self.path_row(self.fields_frame, label, 0, VIDEO_SRC_TYPES)
            if enc:
                ttk.Label(self.fields_frame, text="Message:", style="TLabel").grid(row=1, column=0, sticky="nw", pady=5)
                text = tk.Text(self.fields_frame, width=42, height=4, bg=PANEL, fg=TEXT,
                                insertbackground=NEON_GREEN, font=FONT_MONO,
                                highlightthickness=1, highlightbackground=BORDER, bd=0)
                text.grid(row=1, column=1, columnspan=2, pady=5, sticky="ew")
                self.field_entries["message"] = text
                self.field_entries["out"] = self.path_row(self.fields_frame, "Output video (.avi):", 2, VIDEO_OUT_TYPES, save=True, default_ext=".avi")
                self.note(self.fields_frame, 3, "Output is always lossless FFV1 .avi — any lossy codec would destroy the hidden bits.")

        elif mode == "Image <-> Video":
            if enc:
                self.field_entries["image"] = self.path_row(self.fields_frame, "Image to hide:", 0, IMAGE_TYPES)
                self.field_entries["src"] = self.path_row(self.fields_frame, "Source video (any format):", 1, VIDEO_SRC_TYPES)
                self.field_entries["out"] = self.path_row(self.fields_frame, "Output video (.avi):", 2, VIDEO_OUT_TYPES, save=True, default_ext=".avi")
                self.note(self.fields_frame, 3, "Output is always lossless FFV1 .avi — any lossy codec would destroy the hidden bits.")
            else:
                self.field_entries["src"] = self.path_row(self.fields_frame, "Video with hidden image:", 0, VIDEO_SRC_TYPES)
                self.field_entries["out"] = self.path_row(self.fields_frame, "Save extracted image as:", 1, PNG_OUT_TYPES, save=True, default_ext=".png")

    def collect_args(self):
        mode = self.mode_var.get()
        enc = self.action == "encode"

        def text_of(key):
            return self.field_entries[key].get("1.0", tk.END).rstrip("\n")

        def entry_of(key):
            return self.field_entries[key].get().strip()

        if mode == MODES[0]:
            msg = text_of("message").strip()
            if not msg:
                raise ValueError("Please enter some text.")
            return (msg,)

        if mode == "Message <-> Image":
            if enc:
                src, msg, out = entry_of("src"), text_of("message"), entry_of("out")
                if not src or not msg or not out:
                    raise ValueError("Please provide a source image, message, and output path.")
                return (src, msg, out)
            else:
                src = entry_of("src")
                if not src:
                    raise ValueError("Please select an image.")
                return (src,)

        if mode == "Message <-> Audio":
            if enc:
                src, msg, out = entry_of("src"), text_of("message"), entry_of("out")
                if not src or not msg or not out:
                    raise ValueError("Please provide a source audio file, message, and output path.")
                return (src, msg, out)
            else:
                src = entry_of("src")
                if not src:
                    raise ValueError("Please select an audio file.")
                return (src,)

        if mode == "Image <-> Audio":
            if enc:
                image, src, out = entry_of("image"), entry_of("src"), entry_of("out")
                if not image or not src or not out:
                    raise ValueError("Please provide an image, source audio, and output path.")
                return (image, src, out)
            else:
                src, out = entry_of("src"), entry_of("out")
                if not src or not out:
                    raise ValueError("Please select an audio file and an output path.")
                return (src, out)

        if mode == "Message <-> Video":
            if enc:
                src, msg, out = entry_of("src"), text_of("message"), entry_of("out")
                if not src or not msg or not out:
                    raise ValueError("Please provide a source video, message, and output path.")
                return (src, msg, out)
            else:
                src = entry_of("src")
                if not src:
                    raise ValueError("Please select a video.")
                return (src,)

        if mode == "Image <-> Video":
            if enc:
                image, src, out = entry_of("image"), entry_of("src"), entry_of("out")
                if not image or not src or not out:
                    raise ValueError("Please provide an image, source video, and output path.")
                return (image, src, out)
            else:
                src, out = entry_of("src"), entry_of("out")
                if not src or not out:
                    raise ValueError("Please select a video and an output path.")
                return (src, out)

        raise ValueError("Unknown mode.")

    def start_run(self):
        if self.worker_thread and self.worker_thread.is_alive():
            return
        mode = self.mode_var.get()
        try:
            args = self.collect_args()
        except ValueError as e:
            messagebox.showwarning("Missing info", str(e))
            return

        self.password = self.password_entry.get()
        if mode == MODES[0] and not self.password:
            messagebox.showwarning("Password needed", "Text <-> Cipher requires a password.")
            return
        self.run_btn.config(state="disabled")
        self.progress["value"] = 0
        self.status_var.set("STARTING...")
        self.result_text.delete("1.0", tk.END)
        verb = "encode" if self.action == "encode" else "decode"
        self.log(f"=== Starting {verb}: {mode} ===")

        self.worker_thread = threading.Thread(target=self.run_worker, args=(mode, args), daemon=True)
        self.worker_thread.start()

    def run_worker(self, mode, args):
        enc = self.action == "encode"
        pw = self.password
        pcb, log = self.progress_cb, self.log
        try:
            saved_path = None
            result_message = None
            if mode == MODES[0]:
                (text,) = args
                result_message = encrypt_text(text, pw) if enc else decrypt_text(text, pw)
                log("Text encrypted." if enc else "Text decrypted.")
            elif mode == "Message <-> Image":
                if enc:
                    src, msg, out = args
                    saved_path = encode_message_in_image(src, msg, out, pcb, log, password=pw)
                else:
                    result_message = decode_message_from_image(args[0], pcb, log, password=pw)
            elif mode == "Message <-> Audio":
                if enc:
                    src, msg, out = args
                    saved_path = encode_message_in_audio(src, msg, out, pcb, log, password=pw)
                else:
                    result_message = decode_message_from_audio(args[0], pcb, log, password=pw)
            elif mode == "Image <-> Audio":
                if enc:
                    image, src, out = args
                    saved_path = encode_image_in_audio(image, src, out, pcb, log, password=pw)
                else:
                    src, out = args
                    decode_image_from_audio(src, out, pcb, log, password=pw)
                    saved_path = out
            elif mode == "Message <-> Video":
                if enc:
                    src, msg, out = args
                    saved_path = encode_message_in_video(src, msg, out, pcb, log, password=pw)
                else:
                    result_message = decode_message_from_video(args[0], pcb, log, password=pw)
            elif mode == "Image <-> Video":
                if enc:
                    image, src, out = args
                    saved_path = encode_image_in_video(image, src, out, pcb, log, password=pw)
                else:
                    src, out = args
                    decode_image_from_video(src, out, pcb, log, password=pw)
                    saved_path = out

            self.run_callback(self, True, None, saved_path, result_message)
        except Exception as e:
            self.log(f"ERROR: {e}")
            self.run_callback(self, False, str(e), None, None)

    def on_done(self, ok, err, saved_path, result_message):
        self.run_btn.config(state="normal")
        if ok:
            self.status_var.set("DONE.")
            if result_message is not None:
                self.result_text.delete("1.0", tk.END)
                self.result_text.insert(tk.END, result_message)
                messagebox.showinfo("Success", "Done. The result is in the result box (use COPY).")
            else:
                verb = "Encoding" if self.action == "encode" else "Decoding"
                suffix = f"\nSaved to: {saved_path}" if saved_path else ""
                messagebox.showinfo("Success", f"{verb} completed successfully.{suffix}")
        else:
            self.status_var.set("FAILED.")
            verb = "Encoding" if self.action == "encode" else "Decoding"
            messagebox.showerror(f"{verb} failed", err)

    def on_progress(self, fraction, message):
        self.progress["value"] = fraction * 100
        if message:
            self.status_var.set(message.upper())


class StegoApp:
    def __init__(self, root):
        self.root = root
        root.title("STEGO TOOL // encode & decode")
        root.geometry("820x760")
        root.minsize(680, 620)
        apply_cyber_style(root)

        self.log_queue = queue.Queue()

        header = ttk.Frame(root, style="TFrame", padding=(20, 16, 20, 8))
        header.pack(fill="x")
        ttk.Label(header, text="🔐 STEGO TOOL", style="Title.TLabel").pack(anchor="w")
        ttk.Label(header, text="LSB steganography // image · audio · video — fully local, nothing leaves this machine",
                  style="Muted.TLabel").pack(anchor="w", pady=(2, 0))

        self.notebook = ttk.Notebook(root)
        self.notebook.pack(fill="both", expand=True, padx=16, pady=(4, 8))

        self.encode_panel = ToolPanel(self.notebook, "encode", self.on_panel_done, self.log, self.make_progress_cb())
        self.decode_panel = ToolPanel(self.notebook, "decode", self.on_panel_done, self.log, self.make_progress_cb())
        self.notebook.add(self.encode_panel, text="  ENCODE  ")
        self.notebook.add(self.decode_panel, text="  DECODE  ")

        console_outer = ttk.Frame(root, style="TFrame", padding=(16, 0, 16, 16))
        console_outer.pack(fill="both", expand=False)
        ttk.Label(console_outer, text="> CONSOLE LOG", style="Sub.TLabel").pack(anchor="w")
        self.console = tk.Text(console_outer, height=10, bg="#020403", fg=NEON_GREEN,
                                insertbackground=NEON_GREEN, font=("Consolas", 9),
                                highlightthickness=1, highlightbackground=BORDER, bd=0)
        self.console.pack(fill="both", expand=True, pady=(4, 0))

        try:
            root.iconbitmap(_ICON_PATH)
        except Exception:
            pass

        self.root.after(100, self.poll_log_queue)

    def make_progress_cb(self):
        def cb(fraction, message):
            self.log_queue.put(("progress", (fraction, message)))
        return cb

    def log(self, message):
        timestamp = time.strftime("%H:%M:%S")
        line = f"[{timestamp}] {message}"
        _append_log_file(line)
        self.log_queue.put(("log", line))

    def on_panel_done(self, panel, ok, err, saved_path, result_message):
        self.log_queue.put(("done", (panel, ok, err, saved_path, result_message)))

    def poll_log_queue(self):
        try:
            while True:
                kind, payload = self.log_queue.get_nowait()
                if kind == "log":
                    self.console.insert(tk.END, payload + "\n")
                    self.console.see(tk.END)
                elif kind == "progress":
                    fraction, message = payload
                    active = self.encode_panel if self.notebook.index(self.notebook.select()) == 0 else self.decode_panel
                    active.on_progress(fraction, message)
                elif kind == "done":
                    panel, ok, err, saved_path, result_message = payload
                    panel.on_done(ok, err, saved_path, result_message)
        except queue.Empty:
            pass
        self.root.after(100, self.poll_log_queue)


def main():
    root = tk.Tk()
    StegoApp(root)
    root.mainloop()


if __name__ == "__main__":
    main()
