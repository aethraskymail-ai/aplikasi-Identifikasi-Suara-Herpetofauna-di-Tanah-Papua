"""Pemrosesan massal folder PAR di hardisk.

    python -m suarakatak.batch --masukan I:\\PAR --keluaran I:\\HASIL_EKSTRAKSI\\HASIL [--perch]

- Memilih file berdasarkan jam di nama `YYYYMMDD_HHMMSS.WAV` (default 17:30–21:00).
- Menulis `HASIL\\<PARxxx>\\<tanggal>\\<file>.WAV` (48 kHz PCM s16) + menyalin `CONFIG.TXT`.
- Menulis `ringkasan.csv` (level pita sebelum/sesudah, nada yang di-notch, aktivitas pita katak).
- `--perch`: menambah tebakan Perch dan menyimpan embedding per file ke `embedding/<PAR>/<file>.npz`
  untuk melatih model kustom nanti.
- Bisa dilanjutkan: file yang keluarannya sudah ada dilewati.
"""

from __future__ import annotations

import argparse
import csv
import shutil
import sys
from datetime import time
from pathlib import Path

import numpy as np

from . import deteksi, pipeline
from .audio import dalam_jendela, info_nama_file, muat_audio, simpan_wav

KOLOM = [
    "par", "tanggal", "file", "waktu", "durasi_s", "puncak_dinotch_hz", "gain_db",
    "katak_mean_db_sebelum", "katak_mean_db_sesudah", "dengung_mean_db_sebelum", "dengung_mean_db_sesudah",
    "jangkrik_mean_db_sebelum", "jangkrik_mean_db_sesudah", "detik_aktif_pita_katak", "persen_aktif_pita_katak",
    "perch_amfibi_teratas", "status",
]


def _jam(s: str) -> time:
    h, m = s.split(":")
    return time(int(h), int(m))


def cari_file(masukan: Path, mulai: time, selesai: time):
    for path in sorted(masukan.rglob("*")):
        if path.suffix.lower() not in {".wav", ".flac"} or not path.is_file():
            continue
        info = info_nama_file(path)
        if info.waktu is None or not dalam_jendela(info.waktu.time(), mulai, selesai):
            continue
        yield path, info


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--masukan", required=True, type=Path, help="folder induk PAR001..PAR024")
    ap.add_argument("--keluaran", required=True, type=Path, help="folder HASIL")
    ap.add_argument("--jam", default="17:30-21:00", help="jendela waktu lokal, mis. 17:30-21:00")
    ap.add_argument("--perch", action="store_true", help="jalankan Google Perch v2 (butuh TensorFlow)")
    ap.add_argument("--batas", type=int, default=0, help="proses maksimal N file (uji coba)")
    args = ap.parse_args(argv)

    mulai, selesai = (_jam(s) for s in args.jam.split("-"))
    args.keluaran.mkdir(parents=True, exist_ok=True)
    path_csv = args.keluaran / "ringkasan.csv"
    baru = not path_csv.exists()
    if args.perch:
        from . import perch

    n = 0
    with open(path_csv, "a", newline="", encoding="utf-8") as fcsv:
        w = csv.DictWriter(fcsv, fieldnames=KOLOM)
        if baru:
            w.writeheader()
        for path, info in cari_file(args.masukan, mulai, selesai):
            par = info.par or path.parent.name
            tanggal = info.waktu.strftime("%Y-%m-%d")
            tujuan = args.keluaran / par / tanggal / (path.stem + ".WAV")
            if tujuan.exists():
                continue
            tujuan.parent.mkdir(parents=True, exist_ok=True)
            config = next((p for p in path.parents if (p / "CONFIG.TXT").exists()), None)
            if config and not (tujuan.parent / "CONFIG.TXT").exists():
                shutil.copy2(config / "CONFIG.TXT", tujuan.parent / "CONFIG.TXT")
            baris = {"par": par, "tanggal": tanggal, "file": path.name, "waktu": info.waktu.isoformat(sep=" ")}
            try:
                x, sr = muat_audio(path)
                h = pipeline.jalankan(x, sr)
                simpan_wav(tujuan, h.audio, h.sr)
                seg = deteksi.segmen_aktif(h.audio, h.sr)
                akt = deteksi.ringkas_aktivitas(seg, len(x) / sr)
                ks, kd, kj = "katak (2400–3800 Hz)", "dengung (900–1900 Hz)", "jangkrik (4300–6600 Hz)"
                baris.update(
                    durasi_s=round(len(x) / sr, 2),
                    puncak_dinotch_hz=" ".join(f"{p.frekuensi_hz:.0f}" for p in h.puncak),
                    gain_db=h.gain_db,
                    katak_mean_db_sebelum=h.level_sebelum[ks]["mean_db"],
                    katak_mean_db_sesudah=h.level_sesudah[ks]["mean_db"],
                    dengung_mean_db_sebelum=h.level_sebelum[kd]["mean_db"],
                    dengung_mean_db_sesudah=h.level_sesudah[kd]["mean_db"],
                    jangkrik_mean_db_sebelum=h.level_sebelum[kj]["mean_db"],
                    jangkrik_mean_db_sesudah=h.level_sesudah[kj]["mean_db"],
                    detik_aktif_pita_katak=akt["detik_aktif"],
                    persen_aktif_pita_katak=akt["persen_aktif"],
                    status="ok",
                )
                if args.perch:
                    jendela = perch.analisis(x, sr)
                    agg = np.max(np.stack([j.logit for j in jendela]), axis=0)
                    baris["perch_amfibi_teratas"] = perch.teratas(agg, 1)[0]["label"]
                    emb_path = args.keluaran / "embedding" / par / (path.stem + ".npz")
                    emb_path.parent.mkdir(parents=True, exist_ok=True)
                    np.savez_compressed(
                        emb_path,
                        embedding=np.stack([j.embedding for j in jendela]).astype(np.float16),
                        mulai_s=np.array([j.mulai_s for j in jendela]),
                    )
            except Exception as e:
                baris["status"] = f"gagal: {e}"
                tujuan.unlink(missing_ok=True)
            w.writerow(baris)
            fcsv.flush()
            n += 1
            print(f"[{n}] {par}/{path.name} {baris['status']}", file=sys.stderr)
            if args.batas and n >= args.batas:
                break
    print(f"Selesai: {n} file diproses → {path_csv}", file=sys.stderr)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
