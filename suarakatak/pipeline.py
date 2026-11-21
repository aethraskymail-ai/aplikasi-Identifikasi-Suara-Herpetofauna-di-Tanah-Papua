"""Metode penyaringan yang sudah tervalidasi (catatan "Pipeline Audio Herpet — Drive I:\\PAR").

1. highpass 2100 Hz ×2 + lowpass 8000 Hz ×2 (biquad 2-kutub, Q 0,707, sama dengan default ffmpeg).
2. FFT rata-rata per file → puncak nada sempit di luar pita katak 2,4–3,8 kHz.
3. Notch `equalizer` tajam bertingkat per puncak (g -40..-50 dB, 3 lebar berbeda).
4. Normalisasi berbasis puncak: gain = -2 dB − max_volume. Keluaran 48 kHz PCM s16.
5. Verifikasi level per pita sebelum/sesudah (bandpass FFT tajam).

Tidak memakai afftdn/anlmdn, spectral subtraction, bandreject statis atau loudnorm (gagal di sampel).
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field

import numpy as np
from scipy.signal import find_peaks, medfilt, sosfilt, welch

PITA_KATAK = (2400.0, 3800.0)
HIGHPASS_HZ = 2100.0
LOWPASS_HZ = 8000.0
TARGET_PUNCAK_DB = -2.0
SR_KELUARAN = 48000

# (lebar Hz, gain dB) — notch bertingkat: sempit-dalam, sedang, lebar-dangkal.
TINGKAT_NOTCH = ((5.0, -50.0), (12.0, -45.0), (25.0, -40.0))

PITA_VERIFIKASI = {
    "dengung (900–1900 Hz)": (900.0, 1900.0),
    "serangga berdenyut (1950–2250 Hz)": (1950.0, 2250.0),
    "katak (2400–3800 Hz)": PITA_KATAK,
    "jangkrik (4300–6600 Hz)": (4300.0, 6600.0),
}


def _biquad(b, a) -> np.ndarray:
    b = np.asarray(b, dtype=float) / a[0]
    a = np.asarray(a, dtype=float) / a[0]
    return np.concatenate([b, a])[None, :]


def biquad_highpass(f: float, sr: int, q: float = 0.707) -> np.ndarray:
    w0 = 2 * np.pi * f / sr
    alpha = np.sin(w0) / (2 * q)
    c = np.cos(w0)
    return _biquad([(1 + c) / 2, -(1 + c), (1 + c) / 2], [1 + alpha, -2 * c, 1 - alpha])


def biquad_lowpass(f: float, sr: int, q: float = 0.707) -> np.ndarray:
    w0 = 2 * np.pi * f / sr
    alpha = np.sin(w0) / (2 * q)
    c = np.cos(w0)
    return _biquad([(1 - c) / 2, 1 - c, (1 - c) / 2], [1 + alpha, -2 * c, 1 - alpha])


def biquad_equalizer(f: float, sr: int, lebar_hz: float, gain_db: float) -> np.ndarray:
    """Filter peaking RBJ, setara `equalizer=f=..:t=h:w=..:g=..` di ffmpeg."""
    w0 = 2 * np.pi * f / sr
    a_lin = 10 ** (gain_db / 40)
    alpha = np.sin(w0) / (2 * f / lebar_hz)
    c = np.cos(w0)
    return _biquad(
        [1 + alpha * a_lin, -2 * c, 1 - alpha * a_lin],
        [1 + alpha / a_lin, -2 * c, 1 - alpha / a_lin],
    )


def saring_pita(x: np.ndarray, sr: int) -> np.ndarray:
    lp = min(LOWPASS_HZ, 0.45 * sr)
    sos = np.vstack([biquad_highpass(HIGHPASS_HZ, sr)] * 2 + [biquad_lowpass(lp, sr)] * 2)
    return sosfilt(sos, x).astype(np.float32)


def spektrum_rata(x: np.ndarray, sr: int) -> tuple[np.ndarray, np.ndarray]:
    """FFT rata-rata (Welch, resolusi ~2,9 Hz) dalam dB."""
    nper = min(len(x), 16384 if sr >= 32000 else 8192)
    f, p = welch(x, fs=sr, nperseg=nper, noverlap=nper // 2)
    return f, 10 * np.log10(p + 1e-20)


@dataclass
class Puncak:
    frekuensi_hz: float
    tonjolan_db: float
    level_db: float


def cari_puncak_gangguan(
    x: np.ndarray,
    sr: int,
    f_min: float = 300.0,
    f_max: float = 7800.0,
    tonjolan_min_db: float = 8.0,
    maks_puncak: int = 16,
) -> list[Puncak]:
    """Nada sempit di luar pita katak, dideteksi ulang per file (tidak di-hardcode)."""
    f, db = spektrum_rata(x, sr)
    df = f[1] - f[0]
    kernel = int(round(150.0 / df)) | 1
    dasar = medfilt(db, kernel_size=max(3, kernel))
    menonjol = db - dasar
    lebar_maks = max(2, int(round(40.0 / df)))
    idx, _ = find_peaks(menonjol, height=tonjolan_min_db, width=(None, lebar_maks), distance=max(1, int(8 / df)))
    hasil = []
    for i in idx:
        fi = float(f[i])
        if fi < f_min or fi > min(f_max, 0.45 * sr):
            continue
        if PITA_KATAK[0] - 60 <= fi <= PITA_KATAK[1] + 60:
            continue
        hasil.append(Puncak(round(fi, 1), round(float(menonjol[i]), 1), round(float(db[i]), 1)))
    hasil.sort(key=lambda p: p.level_db, reverse=True)
    return hasil[:maks_puncak]


def notch_bertingkat(x: np.ndarray, sr: int, puncak: list[Puncak]) -> np.ndarray:
    if not puncak:
        return x
    sos = np.vstack(
        [biquad_equalizer(p.frekuensi_hz, sr, lebar, gain) for p in puncak for lebar, gain in TINGKAT_NOTCH]
    )
    return sosfilt(sos, x).astype(np.float32)


def max_volume_db(x: np.ndarray) -> float:
    return float(20 * np.log10(np.max(np.abs(x)) + 1e-12))


def normalisasi_puncak(x: np.ndarray, target_db: float = TARGET_PUNCAK_DB) -> tuple[np.ndarray, float]:
    gain = target_db - max_volume_db(x)
    return (x * 10 ** (gain / 20)).astype(np.float32), round(gain, 2)


def level_pita(x: np.ndarray, sr: int, pita: tuple[float, float]) -> dict[str, float | None]:
    """Level rata-rata (RMS) dan puncak di satu pita, dengan bandpass FFT tajam.

    Bandpass biquad seperti `bandpass` ffmpeg terlalu landai: dengung yang lebih keras dari katak
    bocor ke pengukuran pita katak. Masker FFT memberi angka per pita yang tidak saling bocor.
    """
    lo, hi = pita
    if hi > sr / 2:
        return {"mean_db": None, "max_db": None}
    spek = np.fft.rfft(x)
    f = np.fft.rfftfreq(len(x), 1 / sr)
    spek[(f < lo) | (f > hi)] = 0
    y = np.fft.irfft(spek, n=len(x))
    rms = np.sqrt(np.mean(y**2) + 1e-20)
    return {"mean_db": round(float(20 * np.log10(rms)), 1), "max_db": round(max_volume_db(y), 1)}


@dataclass
class HasilSaring:
    audio: np.ndarray
    sr: int
    puncak: list[Puncak]
    gain_db: float
    level_sebelum: dict[str, dict[str, float]] = field(default_factory=dict)
    level_sesudah: dict[str, dict[str, float]] = field(default_factory=dict)

    def ringkasan(self) -> dict:
        return {
            "puncak_dinotch": [asdict(p) for p in self.puncak],
            "gain_normalisasi_db": self.gain_db,
            "level_sebelum": self.level_sebelum,
            "level_sesudah": self.level_sesudah,
        }


def jalankan(x: np.ndarray, sr: int) -> HasilSaring:
    from .audio import resample

    if sr != SR_KELUARAN and sr > SR_KELUARAN:
        x = resample(x, sr, SR_KELUARAN)
        sr = SR_KELUARAN
    sebelum = {nama: level_pita(x, sr, pita) for nama, pita in PITA_VERIFIKASI.items()}
    y = saring_pita(x, sr)
    puncak = cari_puncak_gangguan(y, sr)
    y = notch_bertingkat(y, sr, puncak)
    sesudah_mentah = {nama: level_pita(y, sr, pita) for nama, pita in PITA_VERIFIKASI.items()}
    y, gain = normalisasi_puncak(y)
    # Level sesudah dilaporkan sebelum normalisasi agar bisa dibandingkan langsung dengan level asal.
    return HasilSaring(y, sr, puncak, gain, sebelum, sesudah_mentah)
