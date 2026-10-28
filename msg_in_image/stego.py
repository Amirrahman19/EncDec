"""Encode/decode a text message inside an image using LSB steganography."""

import os
from PIL import Image
import numpy as np

END_MARKER = b"\x00\x00STEGEND\x00\x00"
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


def _ensure_png(path: str) -> str:
    """Force a .png extension. Any other extension (e.g. reusing the source
    .jpg path) would make PIL save as a lossy format, silently destroying
    the embedded LSBs even though the encode step reports success."""
    root, ext = os.path.splitext(path)
    if ext.lower() != ".png":
        return root + ".png"
    return path


def encode_message_in_image(input_path: str, message: str, output_path: str) -> str:
    img = Image.open(input_path).convert("RGB")
    arr = np.array(img)
    flat = arr.reshape(-1)

    payload = _pack_payload(message.encode("utf-8"))
    bits = list(_bytes_to_bits(payload))

    capacity = flat.size
    if len(bits) > capacity:
        raise ValueError(
            f"Message too large for this image. Capacity: {capacity // 8} bytes, "
            f"needed: {len(bits) // 8} bytes."
        )

    for i, bit in enumerate(bits):
        flat[i] = (flat[i] & 0xFE) | bit

    out_arr = flat.reshape(arr.shape)
    output_path = _ensure_png(output_path)
    Image.fromarray(out_arr, mode="RGB").save(output_path, format="PNG")
    return output_path


def decode_message_from_image(input_path: str) -> str:
    img = Image.open(input_path).convert("RGB")
    arr = np.array(img)
    flat = arr.reshape(-1)

    header_bits = (flat[:HEADER_BITS] & 1).tolist()
    length = _unpack_length(_bits_to_bytes(header_bits))

    total_bits = HEADER_BITS + length * 8
    if total_bits > flat.size:
        raise ValueError("Image does not contain a valid embedded message.")

    payload_bits = (flat[HEADER_BITS:total_bits] & 1).tolist()
    data = _bits_to_bytes(payload_bits)
    return data.decode("utf-8")
