"""Pemrosesan massal folder PAR di hardisk.

    python -m suarakatak.batch --masukan I:\\PAR --keluaran I:\\HASIL_EKSTRAKSI\\HASIL [--perch]

- Memilih file berdasarkan jam di nama `YYYYMMDD_HHMMSS.WAV` (default 17:30–21:00).
- Menulis `HASIL\\<PARxxx>\\<tanggal>\\<file>.WAV` (48 kHz PCM s16) + menyalin `CONFIG.TXT`.
- Menulis `ringkasan.csv` (level pita sebelum/sesudah, nada yang di-notch, aktivitas pita katak).
- `--perch`: menambah tebakan Perch dan menyimpan embedding per file ke `embedding/<PAR>/<file>.npz`
  untuk melatih model kustom nanti.
- Bisa dilanjutkan: hanya hasil dengan baris CSV sukses dan embedding yang diperlukan dilewati.
"""

from __future__ import annotations

import argparse
import csv
import shutil
import sys
import tempfile
from contextlib import contextmanager
from datetime import time
from pathlib import Path

import numpy as np

from . import deteksi, pipeline
from .audio import dalam_jendela, info_nama_file, muat_audio, simpan_wav

KOLOM = [
    "par", "tanggal", "file", "waktu", "durasi_s", "puncak_dinotch_hz", "gain_db",
    "katak_mean_db_sebelum", "katak_mean_db_sesudah", "dengung_mean_db_sebelum", "dengung_mean_db_sesudah",
    "jangkrik_mean_db_sebelum", "jangkrik_mean_db_sesudah", "detik_aktif_pita_katak", "persen_aktif_pita_katak",
    "tebakan_perch_belum_terverifikasi", "status",
]


@contextmanager
def _atomik(path: Path):
    path.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile(dir=path.parent, prefix=".batch-", suffix=path.suffix, delete=False) as f:
        sementara = Path(f.name)
    try:
        yield sementara
        sementara.replace(path)
    finally:
        sementara.unlink(missing_ok=True)


def _kunci(baris):
    return baris["par"], baris["tanggal"], baris["file"]


def _baca_csv(path):
    baris = {}
    if path.exists():
        with path.open(newline="", encoding="utf-8") as f:
            for row in csv.DictReader(f):
                row["tebakan_perch_belum_terverifikasi"] = row.pop(
                    "perch_amfibi_teratas", row.get("tebakan_perch_belum_terverifikasi", "")
                )
                baris[_kunci(row)] = row
    return baris


def _simpan_csv(path, baris):
    with _atomik(path) as sementara:
        with sementara.open("w", newline="", encoding="utf-8") as f:
            w = csv.DictWriter(f, fieldnames=KOLOM)
            w.writeheader()
            w.writerows(baris.values())


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


def _main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--masukan", required=True, type=Path, help="folder induk PAR001..PAR024")
    ap.add_argument("--keluaran", required=True, type=Path, help="folder HASIL")
    ap.add_argument("--jam", default="17:30-21:00", help="jendela waktu lokal, mis. 17:30-21:00")
    ap.add_argument("--perch", action="store_true", help="jalankan Google Perch v2 (butuh TensorFlow)")
    ap.add_argument("--batas", type=int, default=0, help="proses maksimal N file (uji coba)")
    args = ap.parse_args(argv)

    if not args.masukan.is_dir():
        print(f"Galat: folder masukan tidak ditemukan: {args.masukan}. Periksa sambungan hardisk dan jalurnya.", file=sys.stderr)
        return 2
    mulai, selesai = (_jam(s) for s in args.jam.split("-"))
    args.keluaran.mkdir(parents=True, exist_ok=True)
    path_csv = args.keluaran / "ringkasan.csv"
    semua_baris = _baca_csv(path_csv)
    if path_csv.exists():
        _simpan_csv(path_csv, semua_baris)
    if args.perch:
        from . import perch

    n = 0
    ditemukan = 0
    gagal = 0
    for path, info in cari_file(args.masukan, mulai, selesai):
        ditemukan += 1
        par = info.par or path.parent.name
        tanggal = info.waktu.strftime("%Y-%m-%d")
        tujuan = args.keluaran / par / tanggal / (path.stem + ".WAV")
        emb_path = args.keluaran / "embedding" / par / (path.stem + ".npz")
        identitas = {"par": par, "tanggal": tanggal, "file": path.name, "waktu": info.waktu.isoformat(sep=" ")}
        lama = semua_baris.get(_kunci(identitas), {})
        if (tujuan.exists() and lama.get("status") == "ok"
                and (not args.perch or (emb_path.exists() and lama.get("tebakan_perch_belum_terverifikasi")))):
            continue
        baris = dict(lama) if lama.get("status") == "ok" else identitas.copy()
        try:
            tujuan.parent.mkdir(parents=True, exist_ok=True)
            config = next((p for p in path.parents if (p / "CONFIG.TXT").exists()), None)
            if config and not (tujuan.parent / "CONFIG.TXT").exists():
                shutil.copy2(config / "CONFIG.TXT", tujuan.parent / "CONFIG.TXT")
            x = None
            if tujuan.exists():
                try:
                    x, sr = muat_audio(tujuan)
                    if not len(x):
                        x = None
                except Exception:
                    x = None
            if x is None or lama.get("status") != "ok":
                asli, sr_asli = muat_audio(path)
                h = pipeline.jalankan(asli, sr_asli)
                if x is None:
                    with _atomik(tujuan) as sementara:
                        simpan_wav(sementara, h.audio, h.sr)
                    x, sr = muat_audio(tujuan)
                seg = deteksi.segmen_aktif(x, sr)
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
                baris["tebakan_perch_belum_terverifikasi"] = perch.teratas(agg, 1)[0]["label"]
                with _atomik(emb_path) as sementara:
                    np.savez_compressed(
                        sementara,
                        embedding=np.stack([j.embedding for j in jendela]).astype(np.float16),
                        mulai_s=np.array([j.mulai_s for j in jendela]),
                    )
            baris["status"] = "ok"
        except Exception:
            kosong = path.stat().st_size == 0 if path.exists() else False
            baris["status"] = ("gagal: file kosong, tidak dapat dibaca" if kosong else
                               "gagal: audio tidak dapat dibaca atau diproses; periksa file rusak, izin tulis, dan model Perch bila digunakan")
            gagal += 1
        semua_baris[_kunci(baris)] = baris
        _simpan_csv(path_csv, semua_baris)
        n += 1
        print(f"[{n}] {par}/{path.name} {baris['status']}", file=sys.stderr)
        if args.batas and n >= args.batas:
            break
    if not ditemukan:
        print(f"Tidak ada file WAV/FLAC dengan nama bertanggal dalam jendela {args.jam} di {args.masukan}.", file=sys.stderr)
        return 0
    if not n:
        print(f"Tidak ada file baru: semua hasil sudah lengkap → {path_csv}", file=sys.stderr)
    else:
        print(f"Selesai: {n} file diproses, {gagal} gagal → {path_csv}", file=sys.stderr)
    return 1 if gagal else 0


def main(argv=None) -> int:
    try:
        return _main(argv)
    except KeyboardInterrupt:
        print("Dihentikan. Progres tersimpan; jalankan kembali perintah yang sama untuk melanjutkan.", file=sys.stderr)
        return 130


if __name__ == "__main__":
    raise SystemExit(main())
