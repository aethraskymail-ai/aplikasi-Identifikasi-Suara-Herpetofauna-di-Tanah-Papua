"""Satu alur analisis per file: info AudioMoth → penyaringan → deteksi → Perch."""

from __future__ import annotations

import logging

import numpy as np

from . import deteksi, perch, pipeline
from .audio import AudioTidakValid, info_nama_file, muat_audio, simpan_wav


def gambar_spektrogram(x: np.ndarray, sr: int, path, judul: str) -> None:
    import matplotlib

    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    fig, ax = plt.subplots(figsize=(10, 3.2), dpi=110)
    ax.specgram(x, NFFT=2048, Fs=sr, noverlap=1024, cmap="magma", vmin=-150, vmax=-40)
    ax.set_ylim(0, min(8500, sr / 2))
    for f in pipeline.PITA_KATAK:
        ax.axhline(f, color="#7CFC9A", lw=0.8, ls="--")
    ax.set_xlabel("detik")
    ax.set_ylabel("Hz")
    ax.set_title(judul, fontsize=10)
    fig.tight_layout()
    fig.savefig(path)
    plt.close(fig)


def _persen_aktif(segmen: list[dict], a: float, b: float) -> float:
    tumpang = sum(max(0.0, min(b, s["akhir_s"]) - max(a, s["mulai_s"])) for s in segmen)
    return round(100 * tumpang / max(b - a, 1e-6), 1)


def analisis_file(path_asli, folder, nama_file: str, perch_terfilter: bool = False, nama_metadata: str = ""):
    """Mengembalikan (ringkasan JSON, daftar Jendela Perch atau [])."""
    try:
        x, sr = muat_audio(path_asli)
    except Exception as e:
        raise AudioTidakValid("File tidak bisa dibaca sebagai audio (kosong atau rusak). Coba salin ulang dari kartu AudioMoth.") from e
    if not len(x) or sr <= 0 or not np.isfinite(x).all():
        raise AudioTidakValid("File tidak bisa dibaca sebagai audio (kosong atau rusak). Coba salin ulang dari kartu AudioMoth.")
    durasi = len(x) / sr
    if durasi < 1:
        lama = f"{durasi:.1f}".replace(".", ",")
        raise AudioTidakValid(f"Audio terlalu pendek ({lama} detik); minimal 1 detik. Unggah rekaman yang lebih panjang.")
    tidak_terukur = [nama for nama, (_, hi) in pipeline.PITA_VERIFIKASI.items() if hi > sr / 2]
    peringatan = []
    if tidak_terukur:
        peringatan.append(f"Laju sampel {sr} Hz: frekuensi di atas {sr / 2:g} Hz tidak terekam; pita {', '.join(tidak_terukur)} tidak bisa dinilai sepenuhnya. Gunakan rekaman dengan laju sampel lebih tinggi.")
    info = info_nama_file(nama_metadata or nama_file)
    hasil = pipeline.jalankan(x, sr)
    simpan_wav(folder / "terfilter.wav", hasil.audio, hasil.sr)
    gambar_spektrogram(x, sr, folder / "sebelum.png", "Sebelum penyaringan")
    gambar_spektrogram(hasil.audio, hasil.sr, folder / "sesudah.png", "Sesudah penyaringan (pita katak 2,4–3,8 kHz bergaris)")
    segmen = deteksi.segmen_aktif(hasil.audio, hasil.sr)

    jendela, catatan_perch = [], None
    if perch.tersedia():
        try:
            sumber = (hasil.audio, hasil.sr) if perch_terfilter else (x, sr)
            jendela = perch.analisis(*sumber)
        except Exception:  # model tidak bisa diunduh/dimuat: analisis lain tetap jalan
            logging.getLogger(__name__).exception("Perch gagal dimuat")
            catatan_perch = "Model Perch belum bisa digunakan. Penyaringan tetap tersedia; coba analisis lagi nanti untuk memperoleh saran jenis."
    else:
        catatan_perch = "TensorFlow/kagglehub belum terpasang; Perch dilewati."

    ringkasan = {
        "nama_file": nama_file,
        "durasi_s": round(durasi, 2),
        "sample_rate_asli": sr,
        "peringatan": peringatan,
        "audiomoth": {
            "waktu": info.waktu.isoformat(sep=" ") if info.waktu else None,
            "dalam_jendela_1730_2100": info.dalam_jendela,
            "par": info.par,
        },
        "penyaringan": hasil.ringkasan(),
        "aktivitas": {**deteksi.ringkas_aktivitas(segmen, durasi), "segmen": segmen},
        "perch_terfilter": perch_terfilter,
        "catatan_perch": catatan_perch,
        "jendela": [
            {
                "idx": i,
                "mulai_s": j.mulai_s,
                "akhir_s": j.akhir_s,
                "persen_aktif_pita_katak": _persen_aktif(segmen, j.mulai_s, j.akhir_s),
                "perch_amfibi": perch.teratas(j.logit, 3, hanya_amfibi=True),
                "perch_umum": perch.teratas(j.logit, 3, hanya_amfibi=False),
            }
            for i, j in enumerate(jendela)
        ],
    }
    return ringkasan, jendela
