"""Deteksi aktivitas di pita katak (2,4–3,8 kHz) dari audio terfilter."""

from __future__ import annotations

import numpy as np
from scipy.signal import stft

from .pipeline import PITA_KATAK


def energi_pita(x: np.ndarray, sr: int, frame_s: float = 0.1,
                pita: tuple[float, float] = PITA_KATAK) -> tuple[np.ndarray, np.ndarray]:
    nper = int(sr * frame_s)
    f, t, z = stft(x, fs=sr, nperseg=nper, noverlap=0, boundary=None, padded=False)
    p = np.abs(z) ** 2
    m = (f >= pita[0]) & (f <= pita[1])
    return t, 10 * np.log10(p[m].sum(axis=0) + 1e-20)


def segmen_aktif(
    x: np.ndarray,
    sr: int,
    ambang_db: float = 6.0,
    min_durasi_s: float = 0.2,
    gabung_jeda_s: float = 0.3,
    pita: tuple[float, float] = PITA_KATAK,
) -> list[dict]:
    """Energi di atas persentil 5: jeda singkat tetap bisa menjadi acuan derau.

    Ini aktivitas energi pita, bukan bukti keberadaan katak. Rekaman tanpa
    jeda sama sekali tidak menyediakan acuan derau temporal yang independen.
    """
    t, e = energi_pita(x, sr, pita=pita)
    if len(e) == 0:
        return []
    lantai = float(np.percentile(e, 5))
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
        if a - s >= min_durasi_s - 1e-9
    ]


def peringatan_pita_datar(x: np.ndarray, sr: int, ambang_db: float = 6.0,
                          pita: tuple[float, float] = PITA_KATAK) -> str | None:
    """Energi pita hampir konstan (p95 − p5 < ambang): tidak ada jeda sebagai acuan derau."""
    _, e = energi_pita(x, sr, pita=pita)
    if len(e) == 0:
        return None
    rentang = float(np.percentile(e, 95) - np.percentile(e, 5))
    if rentang >= ambang_db:
        return None
    return (f"Energi pita {pita[0]:g}–{pita[1]:g} Hz hampir konstan (rentang p5–p95 {rentang:.1f} dB "
            f"< {ambang_db:g} dB): tidak ada jeda sebagai acuan derau (mis. hujan, desis, perekam rusak "
            "atau senyap), sehingga aktivitas tidak dapat dinilai; 0% bukan bukti tidak ada katak.")


def ringkas_aktivitas(segmen: list[dict], durasi_s: float) -> dict:
    total = sum(s["akhir_s"] - s["mulai_s"] for s in segmen)
    return {
        "jumlah_segmen": len(segmen),
        "detik_aktif": round(total, 1),
        "persen_aktif": round(100 * total / durasi_s, 1) if durasi_s else 0.0,
    }
