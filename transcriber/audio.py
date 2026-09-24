from __future__ import annotations

import struct

PCM_SAMPLE_RATE = 16_000
PCM_CHANNELS = 1
PCM_SAMPLE_BYTES = 2


def pcm_duration_ms(pcm: bytes) -> int:
    return round(len(pcm) / PCM_SAMPLE_BYTES / PCM_SAMPLE_RATE * 1000)


def pcm_to_wav(
    pcm: bytes,
    sample_rate: int = PCM_SAMPLE_RATE,
    channels: int = PCM_CHANNELS,
) -> bytes:
    """Wrap raw s16le PCM in a RIFF container.

    Carril 3 sends headerless PCM (`audio/L16`), which generative audio APIs do
    not accept directly. A 44-byte header costs nothing and avoids a transcode.
    """
    byte_rate = sample_rate * channels * PCM_SAMPLE_BYTES
    block_align = channels * PCM_SAMPLE_BYTES
    header = b"".join(
        [
            b"RIFF",
            struct.pack("<I", 36 + len(pcm)),
            b"WAVEfmt ",
            struct.pack("<IHHIIHH", 16, 1, channels, sample_rate, byte_rate, block_align, 16),
            b"data",
            struct.pack("<I", len(pcm)),
        ]
    )
    return header + pcm
