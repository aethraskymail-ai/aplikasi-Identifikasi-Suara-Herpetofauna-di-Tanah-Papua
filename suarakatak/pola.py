"""Alur analisis gaya Arbimon: templat → pencocokan pola → validasi manual → ringkasan kehadiran.

Templat adalah kotak waktu × frekuensi pada spektrogram suara yang dibersihkan. Templat digeser
sepanjang waktu pada rekaman lain; skor kecocokan adalah korelasi Pearson (normalized cross
correlation) antara spektrogram dB templat dan potongan rekaman, seperti Pattern Matching Arbimon.
Kecocokan hanyalah *kandidat* sampai divalidasi manual sebagai `hadir` atau `tidak`.
"""

from __future__ import annotations

import json
import sqlite3
import threading
import time
import uuid
from datetime import datetime, timedelta
from pathlib import Path

import numpy as np
import soundfile as sf
from scipy.signal import correlate, find_peaks, spectrogram

NFFT = 1024
HOP = 256
F_MAKS_TAMPIL = 12000.0
DETIK_HALAMAN = 60.0
BLOK_S = 300.0
VALIDASI = {"hadir", "tidak"}

_lock = threading.Lock()


class InputTidakValid(ValueError):
    pass


def spektrogram_db(x: np.ndarray, sr: int) -> tuple[np.ndarray, np.ndarray]:
    """(frekuensi Hz, S dB [frekuensi × frame]); frame ke-k mulai pada sampel k·HOP."""
    if len(x) < NFFT:
        x = np.pad(x, (0, NFFT - len(x)))
    f, _, s = spectrogram(x, fs=sr, nperseg=NFFT, noverlap=NFFT - HOP, window="hann", mode="psd")
    return f, (10 * np.log10(s + 1e-14)).astype(np.float32)


def _baris_pita(f: np.ndarray, f_min: float, f_maks: float) -> slice:
    i0 = int(np.searchsorted(f, f_min, side="left"))
    i1 = int(np.searchsorted(f, f_maks, side="right"))
    return slice(i0, max(i1, i0 + 1))


def ambil_patch(path_wav: Path, mulai_s: float, akhir_s: float, f_min: float, f_maks: float) -> np.ndarray:
    with sf.SoundFile(str(path_wav)) as fh:
        sr = fh.samplerate
        fh.seek(int(mulai_s * sr))
        x = fh.read(int((akhir_s - mulai_s) * sr) + NFFT, dtype="float32", always_2d=True).mean(axis=1)
    if len(x) < NFFT:
        raise InputTidakValid("Kotak templat berada di luar rekaman.")
    f, s = spektrogram_db(x, sr)
    lebar = max(2, int(round((akhir_s - mulai_s) * sr / HOP)))
    return s[_baris_pita(f, f_min, f_maks), :lebar]


def korelasi_geser(s: np.ndarray, t: np.ndarray) -> np.ndarray:
    """Korelasi Pearson templat t (F×W) di setiap geseran waktu pada s (F×N)."""
    w = t.shape[1]
    if s.shape[1] < w:
        return np.zeros(0, np.float32)
    t0 = t - t.mean()
    norma_t = float(np.sqrt((t0 ** 2).sum()))
    if norma_t == 0:
        return np.zeros(s.shape[1] - w + 1, np.float32)
    s = s.astype(np.float64)
    pembilang = correlate(s, t0, mode="valid", method="fft")[0]
    n = t.size
    jumlah = np.concatenate([[0.0], np.cumsum(s.sum(axis=0))])
    kuadrat = np.concatenate([[0.0], np.cumsum((s ** 2).sum(axis=0))])
    js = jumlah[w:] - jumlah[:-w]
    ks = kuadrat[w:] - kuadrat[:-w]
    var = np.maximum(ks - js ** 2 / n, 0)
    with np.errstate(invalid="ignore", divide="ignore"):
        r = np.where(var > 1e-9, pembilang / (norma_t * np.sqrt(var)), 0.0)
    return np.clip(r, -1, 1).astype(np.float32)


def cari_cocok(path_wav: Path, patch: np.ndarray, f_min: float, f_maks: float,
               ambang: float, maks: int) -> list[tuple[float, float]]:
    """[(mulai_s, skor)] tertinggi di atas ambang, tanpa tumpang tindih; dibaca per blok 5 menit."""
    w = patch.shape[1]
    hasil: list[tuple[float, float]] = []
    with sf.SoundFile(str(path_wav)) as fh:
        sr = fh.samplerate
        blok = int(BLOK_S * sr) // HOP * HOP
        tumpang = (w + 4) * HOP + NFFT
        mulai = 0
        sebelumnya = -1.0
        while mulai < fh.frames:
            fh.seek(mulai)
            x = fh.read(blok + tumpang, dtype="float32", always_2d=True).mean(axis=1)
            if len(x) < NFFT:
                break
            f, s = spektrogram_db(x, sr)
            band = s[_baris_pita(f, f_min, f_maks)]
            if band.shape[0] != patch.shape[0]:
                raise InputTidakValid("Laju sampel rekaman berbeda dengan templat.")
            r = korelasi_geser(band, patch)
            batas = min(len(r), blok // HOP) if mulai + blok < fh.frames else len(r)
            # Tetangga puncak diambil dari blok sebelah agar batas blok tidak membuat puncak palsu.
            puncak, _ = find_peaks(np.concatenate([[sebelumnya], r, [-1.0]]), height=ambang)
            hasil += [((mulai + (k - 1) * HOP) / sr, float(r[k - 1])) for k in puncak if k - 1 < batas]
            if batas:
                sebelumnya = float(r[batas - 1])
            mulai += blok
    hasil.sort(key=lambda p: -p[1])
    durasi = w * HOP / sr
    terpilih: list[tuple[float, float]] = []
    for t, skor in hasil:
        if all(abs(t - u) >= durasi for u, _ in terpilih):
            terpilih.append((round(t, 3), round(skor, 3)))
        if len(terpilih) >= maks:
            break
    return sorted(terpilih)


def gambar(s: np.ndarray, path_or_buf, lebar_px: int, tinggi_px: int,
           kotak: tuple[float, float, float, float] | None = None, extent=None) -> None:
    import matplotlib

    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    fig = plt.figure(figsize=(lebar_px / 100, tinggi_px / 100), dpi=100)
    ax = fig.add_axes([0, 0, 1, 1])
    ax.set_axis_off()
    lo, hi = (np.percentile(s, [5, 99.7]) if s.size else (0, 1))
    ax.imshow(s, origin="lower", aspect="auto", cmap="magma", vmin=lo, vmax=max(hi, lo + 1),
              extent=extent, interpolation="nearest")
    if kotak:
        from matplotlib.patches import Rectangle

        t0, t1, f0, f1 = kotak
        ax.add_patch(Rectangle((t0, f0), t1 - t0, f1 - f0, fill=False, ec="#7CFC9A", lw=1.5))
    fig.savefig(path_or_buf, format="png")
    plt.close(fig)


def kanvas(path_wav: Path, mulai_s: float, buf) -> None:
    """Spektrogram tanpa sumbu: x = mulai_s..mulai_s+60 dtk (dipotong di akhir), y = 0..12 kHz."""
    with sf.SoundFile(str(path_wav)) as fh:
        sr = fh.samplerate
        total = fh.frames / sr
        fh.seek(int(mulai_s * sr))
        x = fh.read(int(DETIK_HALAMAN * sr), dtype="float32", always_2d=True).mean(axis=1)
    durasi = max(min(DETIK_HALAMAN, total - mulai_s), NFFT / sr)
    f, s = spektrogram_db(x, sr)
    s = s[_baris_pita(f, 0, F_MAKS_TAMPIL)]
    gambar(s, buf, max(200, int(durasi * 20)), 300)


def potongan(path_wav: Path, mulai_s: float, akhir_s: float, f_min: float, f_maks: float, buf) -> None:
    """Gambar kecil sebuah kecocokan dengan konteks 0,5 dtk dan ±600 Hz."""
    with sf.SoundFile(str(path_wav)) as fh:
        sr = fh.samplerate
        a = max(0.0, mulai_s - 0.5)
        fh.seek(int(a * sr))
        x = fh.read(int((akhir_s + 0.5 - a) * sr), dtype="float32", always_2d=True).mean(axis=1)
    f, s = spektrogram_db(x, sr)
    lo, hi = max(0.0, f_min - 600), min(sr / 2, f_maks + 600)
    baris = _baris_pita(f, lo, hi)
    durasi = max(len(x), NFFT) / sr
    gambar(s[baris], buf, 220, 120, kotak=(mulai_s - a, akhir_s - a, f_min, f_maks),
           extent=(0, durasi, f[baris][0], f[baris][-1]))


def _jam(waktu: str | None, offset_s: float) -> datetime | None:
    if not waktu:
        return None
    return datetime.fromisoformat(waktu) + timedelta(seconds=offset_s)


class Pola:
    """Penyimpanan templat, kecocokan, dan riwayat pencarian (SQLite yang sama dengan label)."""

    def __init__(self, path: Path):
        self.path = path
        path.parent.mkdir(parents=True, exist_ok=True)
        with self._db() as db:
            db.executescript(
                """
                CREATE TABLE IF NOT EXISTS templat (
                  id TEXT PRIMARY KEY, nama TEXT, spesies TEXT, rekaman_id TEXT, nama_file TEXT,
                  mulai_s REAL, akhir_s REAL, f_min REAL, f_maks REAL, patch BLOB,
                  baris INTEGER, kolom INTEGER, dibuat REAL
                );
                CREATE TABLE IF NOT EXISTS cocok (
                  id INTEGER PRIMARY KEY AUTOINCREMENT, templat_id TEXT, rekaman_id TEXT,
                  mulai_s REAL, akhir_s REAL, skor REAL, validasi TEXT, divalidasi REAL
                );
                CREATE INDEX IF NOT EXISTS cocok_templat ON cocok(templat_id, rekaman_id);
                CREATE TABLE IF NOT EXISTS pencarian (
                  templat_id TEXT, rekaman_id TEXT, ambang REAL, waktu REAL,
                  PRIMARY KEY (templat_id, rekaman_id)
                );
                """
            )

    def _db(self):
        db = sqlite3.connect(self.path)
        db.row_factory = sqlite3.Row
        return db

    # --- templat -------------------------------------------------------------------------
    def buat_templat(self, rekaman_id: str, nama_file: str, path_wav: Path, mulai_s: float,
                     akhir_s: float, f_min: float, f_maks: float, spesies: str, nama: str = "") -> dict:
        spesies = (spesies or "").strip()
        if not spesies:
            raise InputTidakValid("Isi nama jenis untuk templat.")
        if not 0.05 <= akhir_s - mulai_s <= 10:
            raise InputTidakValid("Panjang kotak templat harus 0,05–10 detik.")
        if mulai_s < 0 or f_min < 0 or f_maks > F_MAKS_TAMPIL or f_maks - f_min < 100:
            raise InputTidakValid("Rentang frekuensi templat harus 0–12.000 Hz dan selebar minimal 100 Hz.")
        f_min, f_maks = round(f_min), round(f_maks)
        patch = ambil_patch(path_wav, mulai_s, akhir_s, f_min, f_maks)
        tid = uuid.uuid4().hex[:12]
        with _lock, self._db() as db:
            db.execute(
                "INSERT INTO templat VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)",
                (tid, (nama or "").strip() or spesies, spesies, rekaman_id, nama_file, round(mulai_s, 3),
                 round(akhir_s, 3), f_min, f_maks, patch.astype(np.float32).tobytes(),
                 patch.shape[0], patch.shape[1], time.time()),
            )
        return self.templat(tid)

    def templat(self, tid: str) -> dict | None:
        rows = self.daftar_templat(tid)
        return rows[0] if rows else None

    def daftar_templat(self, tid: str | None = None) -> list[dict]:
        with self._db() as db:
            rows = db.execute(
                f"""SELECT t.id, t.nama, t.spesies, t.rekaman_id, t.nama_file, t.mulai_s, t.akhir_s,
                          t.f_min, t.f_maks, t.dibuat,
                          (SELECT COUNT(*) FROM pencarian p WHERE p.templat_id = t.id) AS rekaman_dicari,
                          COUNT(c.id) AS cocok,
                          SUM(c.validasi = 'hadir') AS hadir, SUM(c.validasi = 'tidak') AS tidak,
                          SUM(c.id IS NOT NULL AND c.validasi IS NULL) AS belum
                   FROM templat t LEFT JOIN cocok c ON c.templat_id = t.id
                   {"WHERE t.id = ?" if tid else ""}
                   GROUP BY t.id ORDER BY t.dibuat DESC""",
                (tid,) if tid else (),
            ).fetchall()
        return [{**dict(r), "hadir": r["hadir"] or 0, "tidak": r["tidak"] or 0, "belum": r["belum"] or 0}
                for r in rows]

    def patch(self, tid: str) -> np.ndarray | None:
        with self._db() as db:
            r = db.execute("SELECT patch, baris, kolom FROM templat WHERE id=?", (tid,)).fetchone()
        return np.frombuffer(r["patch"], np.float32).reshape(r["baris"], r["kolom"]) if r else None

    def hapus_templat(self, tid: str) -> None:
        with _lock, self._db() as db:
            for tabel in ("cocok", "pencarian"):
                db.execute(f"DELETE FROM {tabel} WHERE templat_id=?", (tid,))
            db.execute("DELETE FROM templat WHERE id=?", (tid,))

    def hapus_rekaman(self, rid: str) -> None:
        with _lock, self._db() as db:
            for tabel in ("cocok", "pencarian"):
                db.execute(f"DELETE FROM {tabel} WHERE rekaman_id=?", (rid,))

    # --- pencocokan --------------------------------------------------------------------------
    def jalankan(self, tid: str, target: list[tuple[str, Path]], ambang: float = 0.5,
                 maks_per_rekaman: int = 20) -> dict:
        t = self.templat(tid)
        patch = self.patch(tid)
        if t is None or patch is None:
            raise KeyError(tid)
        if not 0.1 <= ambang <= 0.99:
            raise InputTidakValid("Ambang skor harus 0,10–0,99.")
        if not 1 <= maks_per_rekaman <= 500:
            raise InputTidakValid("Batas kecocokan per rekaman harus 1–500.")
        durasi = t["akhir_s"] - t["mulai_s"]
        baru, gagal = 0, []
        for rid, path in target:
            try:
                hasil = cari_cocok(path, patch, t["f_min"], t["f_maks"], ambang, maks_per_rekaman)
            except Exception:
                gagal.append(rid)
                continue
            with _lock, self._db() as db:
                db.execute("DELETE FROM cocok WHERE templat_id=? AND rekaman_id=? AND validasi IS NULL", (tid, rid))
                tervalidasi = [r["mulai_s"] for r in db.execute(
                    "SELECT mulai_s FROM cocok WHERE templat_id=? AND rekaman_id=?", (tid, rid))]
                rows = [(tid, rid, m, round(m + durasi, 3), skor) for m, skor in hasil
                        if all(abs(m - v) >= durasi / 2 for v in tervalidasi)]
                db.executemany(
                    "INSERT INTO cocok (templat_id, rekaman_id, mulai_s, akhir_s, skor) VALUES (?,?,?,?,?)", rows)
                db.execute("INSERT OR REPLACE INTO pencarian VALUES (?,?,?,?)", (tid, rid, ambang, time.time()))
            baru += len(rows)
        return {"rekaman_dicari": len(target) - len(gagal), "gagal": len(gagal), "kandidat_baru": baru}

    def daftar_cocok(self, tid: str | None = None, status: str = "semua", mid: int | None = None) -> list[dict]:
        syarat, arg = [], []
        if tid:
            syarat.append("c.templat_id = ?")
            arg.append(tid)
        if mid is not None:
            syarat.append("c.id = ?")
            arg.append(mid)
        if status == "belum":
            syarat.append("c.validasi IS NULL")
        elif status in VALIDASI:
            syarat.append("c.validasi = ?")
            arg.append(status)
        with self._db() as db:
            rows = db.execute(
                f"""SELECT c.*, t.spesies, t.f_min, t.f_maks FROM cocok c JOIN templat t ON t.id = c.templat_id
                    {"WHERE " + " AND ".join(syarat) if syarat else ""}
                    ORDER BY c.skor DESC, c.id""",
                arg,
            ).fetchall()
        return [dict(r) for r in rows]

    def validasi(self, ids: list[int], nilai: str | None) -> int:
        if nilai is not None and nilai not in VALIDASI:
            raise InputTidakValid("Validasi harus 'hadir', 'tidak', atau kosong.")
        with _lock, self._db() as db:
            cur = db.executemany(
                "UPDATE cocok SET validasi=?, divalidasi=? WHERE id=?",
                [(nilai, time.time() if nilai else None, i) for i in ids],
            )
            return cur.rowcount

    def spesies(self) -> list[str]:
        with self._db() as db:
            return [r[0] for r in db.execute("SELECT DISTINCT spesies FROM templat ORDER BY spesies")]

    def hadir_di_rekaman(self, rid: str) -> list[dict]:
        with self._db() as db:
            rows = db.execute(
                """SELECT t.spesies, COUNT(*) n FROM cocok c JOIN templat t ON t.id = c.templat_id
                   WHERE c.rekaman_id = ? AND c.validasi = 'hadir' GROUP BY t.spesies ORDER BY t.spesies""",
                (rid,),
            ).fetchall()
        return [dict(r) for r in rows]

    # --- ringkasan kehadiran ------------------------------------------------------------------
    def status_rekaman(self, spesies: str) -> dict[str, str]:
        """Per rekaman yang sudah dicari: hadir | belum (kandidat belum divalidasi) | tidak."""
        with self._db() as db:
            dicari = {r[0] for r in db.execute(
                """SELECT DISTINCT p.rekaman_id FROM pencarian p JOIN templat t ON t.id = p.templat_id
                   WHERE t.spesies = ?""", (spesies,))}
            rows = db.execute(
                """SELECT c.rekaman_id, c.validasi FROM cocok c JOIN templat t ON t.id = c.templat_id
                   WHERE t.spesies = ?""", (spesies,)).fetchall()
        status = {rid: "tidak" for rid in dicari}
        for r in rows:
            if r["validasi"] == "hadir":
                status[r["rekaman_id"]] = "hadir"
            elif r["validasi"] is None and status.get(r["rekaman_id"]) != "hadir":
                status[r["rekaman_id"]] = "belum"
        return status

    def ringkasan(self, spesies: str, meta: dict[str, dict]) -> dict:
        """Matriks situs × jam dan situs × tanggal ala Arbimon; hanya `hadir` yang terverifikasi."""
        status = {rid: s for rid, s in self.status_rekaman(spesies).items() if rid in meta}
        jam: dict[str, dict[str, dict[str, int]]] = {}
        tanggal: dict[str, dict[str, str]] = {}
        urutan = {"tidak": 0, "belum": 1, "hadir": 2}
        for rid, s in status.items():
            m = meta[rid]
            situs = m.get("par") or "tanpa situs"
            w = _jam(m.get("waktu"), 0)
            kolom_jam = f"{w.hour:02d}" if w else "?"
            sel = jam.setdefault(situs, {}).setdefault(kolom_jam, {"rekaman": 0, "hadir": 0, "belum": 0})
            sel["rekaman"] += 1
            if s != "tidak":
                sel[s] += 1
            tgl = m.get("tanggal") or "?"
            lama = tanggal.setdefault(situs, {}).get(tgl)
            if lama is None or urutan[s] > urutan[lama]:
                tanggal[situs][tgl] = s
        situs_hadir = sum(any(v == "hadir" for v in t.values()) for t in tanggal.values())
        return {
            "spesies": spesies,
            "rekaman_dicari": len(status),
            "rekaman_hadir": sum(s == "hadir" for s in status.values()),
            "rekaman_belum_divalidasi": sum(s == "belum" for s in status.values()),
            "situs_dicari": len(tanggal),
            "situs_hadir": situs_hadir,
            "okupansi_naif": round(situs_hadir / len(tanggal), 3) if tanggal else None,
            "jam": jam,
            "tanggal": tanggal,
        }


def kode_matriks(s: str | None) -> str:
    """Kode CSV matriks deteksi: 1 hadir tervalidasi, 0 dicari tanpa kandidat tersisa, ? belum divalidasi, NA tidak dicari."""
    return {"hadir": "1", "tidak": "0", "belum": "?"}.get(s or "", "NA")


def simpan_json(path: Path, data) -> None:
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps(data))
    tmp.replace(path)
