"""Encode/decode a text message inside a WAV audio file using LSB steganography."""

import wave
import numpy as np

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


def _read_wav(path: str):
    with wave.open(path, "rb") as wf:
        params = wf.getparams()
        n_frames = wf.getnframes()
        raw = wf.readframes(n_frames)
    sampwidth = params.sampwidth
    dtype = {1: np.uint8, 2: np.int16, 4: np.int32}.get(sampwidth)
    if dtype is None:
        raise ValueError(f"Unsupported sample width: {sampwidth} bytes")
    samples = np.frombuffer(raw, dtype=dtype).copy()
    return params, samples


def encode_message_in_audio(input_path: str, message: str, output_path: str) -> None:
    params, samples = _read_wav(input_path)

    payload = _pack_payload(message.encode("utf-8"))
    bits = list(_bytes_to_bits(payload))

    capacity = samples.size
    if len(bits) > capacity:
        raise ValueError(
            f"Message too large for this audio file. Capacity: {capacity // 8} bytes, "
            f"needed: {len(bits) // 8} bytes."
        )

    original_dtype = samples.dtype
    work = samples.astype(np.int64)
    for i, bit in enumerate(bits):
        work[i] = (work[i] & ~1) | bit
    samples = work.astype(original_dtype)

    with wave.open(output_path, "wb") as wf:
        wf.setparams(params)
        wf.writeframes(samples.tobytes())


def decode_message_from_audio(input_path: str) -> str:
    _, samples = _read_wav(input_path)

    header_bits = (samples[:HEADER_BITS].astype(np.int64) & 1).tolist()
    length = _unpack_length(_bits_to_bytes(header_bits))

    total_bits = HEADER_BITS + length * 8
    if total_bits > samples.size:
        raise ValueError("Audio file does not contain a valid embedded message.")

    payload_bits = (samples[HEADER_BITS:total_bits].astype(np.int64) & 1).tolist()
    data = _bits_to_bytes(payload_bits)
    return data.decode("utf-8")
