"""Membaca audio dan metadata nama file AudioMoth."""

from __future__ import annotations

import re
import shutil
import subprocess
from dataclasses import dataclass
from datetime import datetime, time
from pathlib import Path

import numpy as np
import soundfile as sf
from scipy.signal import resample_poly

AUDIOMOTH_NAME = re.compile(r"(\d{8})_(\d{6})")

JENDELA_MULAI = time(17, 30)
JENDELA_SELESAI = time(21, 0)


class AudioTidakValid(ValueError):
    pass


@dataclass
class InfoAudioMoth:
    waktu: datetime | None
    dalam_jendela: bool | None
    par: str | None


def info_nama_file(path: str | Path) -> InfoAudioMoth:
    """`YYYYMMDD_HHMMSS.WAV` (waktu lokal WIT) dan folder `PARxxx` bila ada."""
    p = Path(path)
    par = next((part for part in reversed(p.parts) if re.fullmatch(r"PAR\d{3}", part, re.I)), None)
    m = AUDIOMOTH_NAME.search(p.stem)
    if not m:
        return InfoAudioMoth(None, None, par)
    try:
        waktu = datetime.strptime(m.group(1) + m.group(2), "%Y%m%d%H%M%S")
    except ValueError:
        return InfoAudioMoth(None, None, par)
    return InfoAudioMoth(waktu, dalam_jendela(waktu.time()), par)


def dalam_jendela(t: time, mulai: time = JENDELA_MULAI, selesai: time = JENDELA_SELESAI) -> bool:
    return mulai <= t <= selesai


def muat_audio(path: str | Path) -> tuple[np.ndarray, int]:
    """Mono float32 [-1, 1]. WAV/FLAC/OGG lewat soundfile, format lain (MP3, M4A) lewat ffmpeg."""
    path = Path(path)
    try:
        data, sr = sf.read(str(path), dtype="float32", always_2d=True)
        return data.mean(axis=1), int(sr)
    except Exception:
        if not shutil.which("ffmpeg"):
            raise
    out = subprocess.run(
        ["ffmpeg", "-v", "error", "-i", str(path), "-ac", "1", "-f", "f32le", "-"],
        check=True,
        capture_output=True,
    ).stdout
    probe = subprocess.run(
        ["ffprobe", "-v", "error", "-select_streams", "a:0", "-show_entries", "stream=sample_rate",
         "-of", "csv=p=0", str(path)],
        check=True,
        capture_output=True,
        text=True,
    ).stdout.strip()
    return np.frombuffer(out, dtype=np.float32).copy(), int(probe.split(",")[0])


def resample(x: np.ndarray, sr: int, sr_baru: int) -> np.ndarray:
    if sr == sr_baru:
        return x
    g = np.gcd(sr, sr_baru)
    return resample_poly(x, sr_baru // g, sr // g).astype(np.float32)


def simpan_wav(path: str | Path, x: np.ndarray, sr: int) -> None:
    sf.write(str(path), np.clip(x, -1, 1), sr, subtype="PCM_16")
