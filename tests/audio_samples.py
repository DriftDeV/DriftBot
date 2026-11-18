"""File audio minimi ma VALIDI (riconosciuti dal controllo sul contenuto) per i test."""

import io
import struct
import wave
import zipfile
from pathlib import Path


def wav_bytes(seconds: float = 1.0, rate: int = 8000) -> bytes:
    buf = io.BytesIO()
    with wave.open(buf, "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(rate)
        w.writeframes(struct.pack("<h", 0) * int(seconds * rate))
    return buf.getvalue()


MP3 = b"ID3\x03\x00\x00\x00\x00\x00\x00" + b"\xff\xfb\x90\x00" * 50
OGG = b"OggS\x00\x02" + b"\x00" * 60
FLAC = b"fLaC" + b"\x00" * 60
M4A = b"\x00\x00\x00\x20ftypM4A " + b"\x00" * 60


def write(path: Path, data: bytes) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(data)
    return path


def zip_bytes(files: dict[str, bytes]) -> bytes:
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as z:
        for name, data in files.items():
            z.writestr(name, data)
    return buf.getvalue()
