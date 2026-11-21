"""Deteksi aktivitas di pita katak (2,4–3,8 kHz) dari audio terfilter."""

from __future__ import annotations

import numpy as np
from scipy.signal import stft

from .pipeline import PITA_KATAK


def energi_pita(x: np.ndarray, sr: int, frame_s: float = 0.1) -> tuple[np.ndarray, np.ndarray]:
    nper = int(sr * frame_s)
    f, t, z = stft(x, fs=sr, nperseg=nper, noverlap=0, boundary=None, padded=False)
    p = np.abs(z) ** 2
    m = (f >= PITA_KATAK[0]) & (f <= PITA_KATAK[1])
    return t, 10 * np.log10(p[m].sum(axis=0) + 1e-20)


def segmen_aktif(
    x: np.ndarray,
    sr: int,
    ambang_db: float = 6.0,
    min_durasi_s: float = 0.2,
    gabung_jeda_s: float = 0.3,
) -> list[dict]:
    """Segmen yang energinya > lantai derau (persentil 20) + ambang."""
    t, e = energi_pita(x, sr)
    if len(e) == 0:
        return []
    lantai = float(np.percentile(e, 20))
    aktif = e > lantai + ambang_db
    dt = t[1] - t[0] if len(t) > 1 else 0.1
    segmen: list[list[float]] = []
    for i, a in enumerate(aktif):
        if not a:
            continue
        mulai, akhir = t[i] - dt / 2, t[i] + dt / 2
        if segmen and mulai - segmen[-1][1] <= gabung_jeda_s:
            segmen[-1][1] = akhir
            segmen[-1][2] = max(segmen[-1][2], e[i] - lantai)
        else:
            segmen.append([mulai, akhir, e[i] - lantai])
    return [
        {"mulai_s": round(max(0.0, s), 2), "akhir_s": round(a, 2), "snr_db": round(float(snr), 1)}
        for s, a, snr in segmen
        if a - s >= min_durasi_s
    ]


def ringkas_aktivitas(segmen: list[dict], durasi_s: float) -> dict:
    total = sum(s["akhir_s"] - s["mulai_s"] for s in segmen)
    return {
        "jumlah_segmen": len(segmen),
        "detik_aktif": round(total, 1),
        "persen_aktif": round(100 * total / durasi_s, 1) if durasi_s else 0.0,
    }
