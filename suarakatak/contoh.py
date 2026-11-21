"""Rekaman contoh sintetis bergaya AudioMoth (PAR001, 29 Apr 18:30) untuk mencoba aplikasi.

Isinya meniru profil gangguan di catatan: dengung 8+ nada (lebih keras dari katak),
serangga berdenyut 2063 Hz, jangkrik 4,5–6,3 kHz, dan pulsa "katak" di sekitar 2.940 Hz.
Ini BUKAN suara katak asli; skor Perch untuk file ini tidak bermakna.
"""

from __future__ import annotations

import numpy as np

SR = 48000


def buat(durasi_s: float = 60.0, seed: int = 7) -> np.ndarray:
    rng = np.random.default_rng(seed)
    t = np.arange(int(SR * durasi_s)) / SR
    x = 0.004 * rng.standard_normal(len(t))
    for f, a in [(1000, 0.05), (1330, 0.04), (1416, 0.035), (1550, 0.03), (1677, 0.03),
                 (1806, 0.025), (1210, 0.02), (1930, 0.015)]:
        x += a * np.sin(2 * np.pi * f * t + rng.uniform(0, 6.28))
    x += 0.0018 * np.sin(2 * np.pi * 2063 * t) * (np.sin(2 * np.pi * 9 * t) > 0)
    for f in (4492, 5133, 5537, 6341):
        x += 0.0035 * np.sin(2 * np.pi * f * t) * (np.sin(2 * np.pi * 30 * t + f) > 0.2)
    # Panggilan katak: rangkaian pulsa 2,94 kHz (FM kecil), tiap ~4 detik, 8 pulsa per panggilan.
    for mulai in np.arange(2.0, durasi_s - 2, 4.3):
        if rng.random() < 0.25:
            continue
        for k in range(8):
            t0 = mulai + k * 0.09
            n = int(0.035 * SR)
            i0 = int(t0 * SR)
            tt = np.arange(n) / SR
            env = np.hanning(n)
            f = 2940 + 120 * (tt / tt[-1] - 0.5)
            x[i0 : i0 + n] += 0.03 * env * np.sin(2 * np.pi * np.cumsum(f) / SR)
    return (x / np.max(np.abs(x)) * 0.7).astype(np.float32)
