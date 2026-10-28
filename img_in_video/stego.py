"""Encode/decode an entire image inside a video using LSB steganography.

Output is always written as a lossless FFV1-encoded AVI, since any lossy
compression (H.264, MJPEG, etc.) would destroy the embedded LSBs.
"""

import io
import cv2
import numpy as np
from PIL import Image

HEADER_BITS = 32


def _bytes_to_bits(data: bytes):
    for byte in data:
        for i in range(7, -1, -1):
            yield (byte >> i) & 1


def _bits_to_bytes(bits):
    data = bytearray()
    byte = 0
    count = 0
    for bit in bits:
        byte = (byte << 1) | bit
        count += 1
        if count == 8:
            data.append(byte)
            byte = 0
            count = 0
    return bytes(data)


def _pack_payload(data: bytes) -> bytes:
    return len(data).to_bytes(4, "big") + data


def _unpack_length(header_bytes: bytes) -> int:
    return int.from_bytes(header_bytes[:4], "big")


def _read_video_frames(path: str):
    cap = cv2.VideoCapture(path)
    if not cap.isOpened():
        raise ValueError(f"Could not open video: {path}")
    fps = cap.get(cv2.CAP_PROP_FPS) or 25.0
    frames = []
    while True:
        ret, frame = cap.read()
        if not ret:
            break
        frames.append(frame)
    cap.release()
    if not frames:
        raise ValueError("Video contains no readable frames.")
    return frames, fps


def _write_video_frames(frames, fps, output_path: str) -> None:
    h, w = frames[0].shape[:2]
    fourcc = cv2.VideoWriter_fourcc(*"FFV1")
    vw = cv2.VideoWriter(output_path, fourcc, fps, (w, h))
    if not vw.isOpened():
        raise RuntimeError("Could not open lossless video writer (FFV1/AVI).")
    for frame in frames:
        vw.write(frame)
    vw.release()


def encode_image_in_video(image_path: str, video_path: str, output_path: str) -> str:
    img = Image.open(image_path).convert("RGB")
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    image_bytes = buf.getvalue()

    frames, fps = _read_video_frames(video_path)
    stacked = np.stack(frames)
    flat = stacked.reshape(-1)

    payload = _pack_payload(image_bytes)
    bits = list(_bytes_to_bits(payload))

    capacity = flat.size
    if len(bits) > capacity:
        raise ValueError(
            f"Image too large for this video. Capacity: {capacity // 8} bytes, "
            f"needed: {len(bits) // 8} bytes. Try a smaller image or longer video."
        )

    for i, bit in enumerate(bits):
        flat[i] = (flat[i] & 0xFE) | bit

    if not output_path.lower().endswith(".avi"):
        output_path = output_path.rsplit(".", 1)[0] + ".avi" if "." in output_path else output_path + ".avi"
    _write_video_frames(list(stacked), fps, output_path)
    return output_path


def decode_image_from_video(video_path: str, output_image_path: str) -> None:
    frames, _ = _read_video_frames(video_path)
    stacked = np.stack(frames)
    flat = stacked.reshape(-1)

    header_bits = (flat[:HEADER_BITS] & 1).tolist()
    length = _unpack_length(_bits_to_bytes(header_bits))

    total_bits = HEADER_BITS + length * 8
    if total_bits > flat.size:
        raise ValueError("Video does not contain a valid embedded image.")

    payload_bits = (flat[HEADER_BITS:total_bits] & 1).tolist()
    data = _bits_to_bytes(payload_bits)

    img = Image.open(io.BytesIO(data))
    img.save(output_image_path)
