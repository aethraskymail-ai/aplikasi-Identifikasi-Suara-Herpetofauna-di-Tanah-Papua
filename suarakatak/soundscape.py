"""Soundscape gaya Arbimon: puncak spektrum per bin 86 Hz, diagregasi per jam.

Tiap rekaman dipotong per 60 detik; untuk setiap potongan dicari puncak spektrum rata-rata
(Welch) yang menonjol ≥ `PROMINENSI_DB`. Nilai sel = proporsi potongan pada jam itu yang punya
puncak di bin frekuensi tersebut. Ini gambaran komposisi suara, bukan identifikasi jenis.
"""

from __future__ import annotations

import json
import uuid
from datetime import datetime, timedelta
from pathlib import Path

import numpy as np
from scipy.signal import find_peaks, welch

from .audio import muat_audio

BIN_HZ = 86.13
F_MAKS = 12000.0
SEGMEN_S = 60.0
PROMINENSI_DB = 6.0
VERSI = 1
N_BIN = int(np.ceil(F_MAKS / BIN_HZ))


def puncak_segmen(x: np.ndarray, sr: int, prominensi_db: float = PROMINENSI_DB) -> list[int]:
    nper = min(len(x), 4096)
    f, p = welch(x, fs=sr, nperseg=nper, noverlap=nper // 2)
    idx = np.minimum((f / BIN_HZ).astype(int), N_BIN)
    daya = np.bincount(idx, weights=p, minlength=N_BIN + 1)[:N_BIN]
    jumlah = np.bincount(idx, minlength=N_BIN + 1)[:N_BIN]
    ada = jumlah > 0
    db = np.full(N_BIN, np.nan)
    db[ada] = 10 * np.log10(daya[ada] / jumlah[ada] + 1e-20)
    lantai = np.nanmin(db) if ada.any() else 0.0
    puncak, _ = find_peaks(np.nan_to_num(db, nan=lantai), prominence=prominensi_db)
    return [int(i) for i in puncak]


def hitung(path_asli: Path, cache: Path) -> list[dict]:
    """[{offset_s, bin: [...]}] per 60 dtk; disimpan di cache agar tidak dihitung ulang."""
    if cache.exists():
        data = json.loads(cache.read_text())
        if data.get("versi") == VERSI:
            return data["segmen"]
    x, sr = muat_audio(path_asli)
    n = int(SEGMEN_S * sr)
    segmen = []
    for i in range(0, len(x), n):
        potong = x[i:i + n]
        if len(potong) < sr:  # sisa < 1 detik tidak cukup untuk spektrum yang stabil
            continue
        segmen.append({"offset_s": i / sr, "bin": puncak_segmen(potong, sr)})
    tmp = cache.with_name(f"{cache.name}.{uuid.uuid4().hex}.tmp")
    tmp.write_text(json.dumps({"versi": VERSI, "segmen": segmen}))
    tmp.replace(cache)
    return segmen


def agregasi(rekaman: list[tuple[str | None, list[dict]]]) -> dict:
    """rekaman = [(waktu mulai ISO atau None, segmen)]. Jam dari waktu + offset bila diketahui."""
    dengan_jam = [r for r in rekaman if r[0]]
    pakai_jam_lokal = bool(dengan_jam)
    dipakai = dengan_jam if pakai_jam_lokal else rekaman
    n_kolom = 24
    if not pakai_jam_lokal:
        n_kolom = max([1] + [int(s["offset_s"] // 3600) + 1 for _, seg in dipakai for s in seg])
    hitung_puncak = np.zeros((N_BIN, n_kolom))
    n_segmen = np.zeros(n_kolom, int)
    for waktu, seg in dipakai:
        for s in seg:
            if pakai_jam_lokal:
                kolom = (datetime.fromisoformat(waktu) + timedelta(seconds=s["offset_s"])).hour
            else:
                kolom = int(s["offset_s"] // 3600)
            n_segmen[kolom] += 1
            for b in s["bin"]:
                hitung_puncak[b, kolom] += 1
    with np.errstate(invalid="ignore", divide="ignore"):
        proporsi = np.where(n_segmen > 0, hitung_puncak / np.maximum(n_segmen, 1), np.nan)
    return {
        "sumbu": "jam WIT" if pakai_jam_lokal else "jam sejak awal rekaman",
        "rekaman": len(dipakai),
        "rekaman_tanpa_jam_dilewati": len(rekaman) - len(dipakai),
        "segmen_per_kolom": n_segmen.tolist(),
        "bin_hz": BIN_HZ,
        "proporsi": proporsi,
    }


def gambar(hasil: dict, buf, judul: str) -> None:
    import matplotlib

    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    p = hasil["proporsi"]
    n_kolom = p.shape[1]
    fig, ax = plt.subplots(figsize=(max(6, min(14, 2 + n_kolom * 0.45)), 4), dpi=110)
    cmap = plt.get_cmap("viridis").copy()
    cmap.set_bad("#eeeeee")
    im = ax.imshow(np.ma.masked_invalid(p), origin="lower", aspect="auto", cmap=cmap, vmin=0, vmax=1,
                   extent=(-0.5, n_kolom - 0.5, 0, N_BIN * BIN_HZ), interpolation="nearest")
    fig.colorbar(im, ax=ax, label="proporsi menit dengan puncak")
    for f in (2400, 3800):
        ax.axhline(f, color="#ff5c5c", lw=0.7, ls="--")
    ax.set_xlabel(hasil["sumbu"])
    ax.set_ylabel("Hz")
    ax.set_xticks(range(n_kolom))
    ax.set_xticklabels([f"{k:02d}" for k in range(n_kolom)], fontsize=7)
    ax.set_title(judul, fontsize=10)
    fig.tight_layout()
    fig.savefig(buf, format="png")
    plt.close(fig)
