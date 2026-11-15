"""Generate the HEV-1 notification tones (frontend/public/audio/*.wav).

The tones are synthesized sine sequences (no third-party audio). The WAV files
carry a RIFF INFO comment acknowledging AI-assisted generation, as required by
the NASA Space Apps project submission guidance for generated audio.

Usage:  python tools/generate_tones.py
"""
from __future__ import annotations

import math
import struct
from pathlib import Path

SR = 22050
OUT = Path(__file__).resolve().parents[1] / "frontend" / "public" / "audio"
COMMENT = b"ORION-MED HEV-1 tone. Synthesized by a script written with AI assistance (Claude, Anthropic). See AI_ATTRIBUTION.md."


def tone(freq: float, dur: float, amp: float = 0.5) -> list[float]:
    n = int(SR * dur)
    out = []
    for i in range(n):
        env = min(1.0, i / (0.01 * SR), (n - i) / (0.02 * SR))
        out.append(amp * env * (math.sin(2 * math.pi * freq * i / SR) + 0.25 * math.sin(4 * math.pi * freq * i / SR)) / 1.25)
    return out


def silence(dur: float) -> list[float]:
    return [0.0] * int(SR * dur)


def write(name: str, samples: list[float]) -> None:
    pcm = b"".join(struct.pack("<h", int(max(-1.0, min(1.0, s)) * 32000)) for s in samples)
    text = COMMENT + b"\x00"
    if len(text) % 2:
        text += b"\x00"
    info = b"INFO" + b"ICMT" + struct.pack("<I", len(text)) + text
    fmt = struct.pack("<HHIIHH", 1, 1, SR, SR * 2, 2, 16)
    body = b"WAVE" + b"fmt " + struct.pack("<I", 16) + fmt + b"LIST" + struct.pack("<I", len(info)) + info
    body += b"data" + struct.pack("<I", len(pcm)) + pcm
    (OUT / name).write_bytes(b"RIFF" + struct.pack("<I", len(body)) + body)


if __name__ == "__main__":
    OUT.mkdir(parents=True, exist_ok=True)
    write("advisory.wav", tone(1046, 0.12, 0.35) + silence(0.05) + tone(1318, 0.18, 0.35))
    write("caution.wav", tone(620, 0.55, 0.55))
    write("warning.wav", (tone(960, 0.22, 0.6) + tone(740, 0.22, 0.6)) * 3)
    print(f"Tones written to {OUT}")
