"""Server web: `uvicorn suarakatak.server:app --port 8000`."""

from __future__ import annotations

import csv
import io
import json
import logging
import os
import re
import shutil
import uuid
from pathlib import Path

import soundfile as sf
from fastapi import FastAPI, File, Form, HTTPException, Request, UploadFile
from fastapi.responses import FileResponse, Response, StreamingResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from . import __version__, contoh, kelompok, perch, soundscape
from .analisis import analisis_file
from .audio import AudioTidakValid, simpan_wav
from .klasifikasi import Penyimpanan
from .pola import InputTidakValid, Pola, kode_matriks
from . import pola as pola_mod

DATA_DIR = Path(os.environ.get("SUARAKATAK_DATA", Path.home() / ".suarakatak")).expanduser()
FOLDER_REKAMAN = DATA_DIR / "rekaman"
STATIC = Path(__file__).parent / "static"
EKSTENSI = {".wav", ".flac", ".mp3", ".m4a", ".ogg", ".aac", ".mpga"}
logger = logging.getLogger(__name__)

app = FastAPI(title="Identifikasi Suara Herpetofauna Tanah Papua", version=__version__)
db = Penyimpanan(DATA_DIR / "suarakatak.sqlite")
pola = Pola(DATA_DIR / "suarakatak.sqlite")


def _folder(rid: str) -> Path:
    if not re.fullmatch(r"[0-9a-f]{12}", rid):
        raise HTTPException(404)
    return FOLDER_REKAMAN / rid


def _proses(path_asli: Path, folder: Path, rid: str, nama: str, perch_terfilter: bool,
            path_relatif: str = "", mode_rendah: bool = False) -> dict:
    ringkasan, jendela = analisis_file(
        path_asli, folder, nama, perch_terfilter=perch_terfilter,
        nama_metadata=path_relatif.replace("\\", "/"), mode_rendah=mode_rendah)
    ringkasan["id"] = rid
    ringkasan["file_asli"] = path_asli.name
    db.simpan_rekaman(rid, nama, ringkasan, jendela)
    return detail(rid)


@app.get("/api/status")
def status() -> dict:
    return {
        "versi": __version__,
        "perch_tersedia": perch.tersedia(),
        "perch_model": perch.HANDLE,
        "jumlah_label_amfibi_perch": len(perch.label_amfibi()),
        "label": db.statistik_label(),
        "model": db.info_model(),
    }


@app.post("/api/analisis")
def analisis(file: UploadFile = File(...), perch_terfilter: bool = Form(False),
             path_relatif: str = Form(""), mode_rendah: bool = Form(False)) -> dict:
    nama = Path(file.filename or "rekaman.wav").name
    ext = Path(nama).suffix.lower()
    if ext not in EKSTENSI:
        raise HTTPException(400, "Jenis file ini belum didukung. Coba file WAV, FLAC, MP3, M4A, atau OGG.")
    rid = uuid.uuid4().hex[:12]
    folder = FOLDER_REKAMAN / rid
    path_asli = folder / f"asli{ext}"
    try:
        folder.mkdir(parents=True)
        with open(path_asli, "wb") as f:
            shutil.copyfileobj(file.file, f)
        if not path_asli.stat().st_size:
            raise AudioTidakValid("File kosong. Coba salin ulang dari kartu AudioMoth.")
        return _proses(path_asli, folder, rid, nama, perch_terfilter=perch_terfilter,
                       path_relatif=path_relatif, mode_rendah=mode_rendah)
    except Exception as e:
        logger.exception("Analisis unggahan gagal: %s", rid)
        try:
            db.hapus_rekaman(rid)
        except Exception:
            logger.exception("Pembersihan basis data gagal: %s", rid)
        shutil.rmtree(folder, ignore_errors=True)
        if isinstance(e, AudioTidakValid):
            raise HTTPException(422, f"{nama}: {e} Coba file WAV lain.") from e
        raise HTTPException(500, "Analisis gagal karena gangguan server. Coba lagi nanti atau gunakan rekaman lain.") from e


@app.post("/api/contoh")
def analisis_contoh() -> dict:
    rid = uuid.uuid4().hex[:12]
    folder = FOLDER_REKAMAN / rid
    folder.mkdir(parents=True)
    path_asli = folder / "asli.wav"
    simpan_wav(path_asli, contoh.buat(), contoh.SR)
    return _proses(path_asli, folder, rid, "PAR001/20260429_183000.WAV (contoh sintetis)", False)


@app.get("/api/rekaman")
def daftar() -> list[dict]:
    return db.daftar_rekaman()


@app.get("/api/rekaman/{rid}")
def detail(rid: str) -> dict:
    data = db.ambil_rekaman(rid)
    if data is None:
        raise HTTPException(404, "Rekaman tidak ditemukan")
    prediksi = db.prediksi(db.embedding_rekaman(rid)) if data.get("jendela") else []
    for j, p in zip(data.get("jendela", []), prediksi):
        j["model_kustom"] = p
        j["data_latih"] = db.data_latih_model(rid, j["idx"])
    data["hadir_tervalidasi"] = pola.hadir_di_rekaman(rid)
    data["model_kustom_aktif"] = db.model() is not None
    data["model"] = db.info_model()
    return data


@app.delete("/api/rekaman/{rid}")
def hapus(rid: str) -> dict:
    folder = _folder(rid)
    db.hapus_rekaman(rid)
    pola.hapus_rekaman(rid)
    shutil.rmtree(folder, ignore_errors=True)
    return {"ok": True}


@app.get("/api/rekaman/{rid}/audio/{jenis}")
def audio(rid: str, jenis: str):
    folder = _folder(rid)
    if jenis == "terfilter":
        path = folder / "terfilter.wav"
    elif jenis == "asli":
        path = next(folder.glob("asli.*"), None)
    else:
        raise HTTPException(404)
    if not path or not path.exists():
        raise HTTPException(404)
    return FileResponse(path)


@app.get("/api/rekaman/{rid}/spektrogram/{jenis}.png")
def spektrogram(rid: str, jenis: str):
    if jenis not in {"sebelum", "sesudah"}:
        raise HTTPException(404)
    path = _folder(rid) / f"{jenis}.png"
    if not path.exists():
        raise HTTPException(404)
    return FileResponse(path, media_type="image/png")


@app.get("/api/rekaman/{rid}/jendela/{idx}/audio.wav")
def audio_jendela(rid: str, idx: int, request: Request):
    path = _folder(rid) / "terfilter.wav"
    waktu = db.waktu_jendela(rid, idx)
    if waktu is None or not path.is_file():
        raise HTTPException(404, "Potongan audio tidak ditemukan.")
    buf = io.BytesIO()
    with sf.SoundFile(path) as wav:
        mulai, akhir = (min(wav.frames, round(t * wav.samplerate)) for t in waktu)
        wav.seek(mulai)
        sf.write(buf, wav.read(akhir - mulai, dtype="int16"), wav.samplerate, format="WAV")
    isi = buf.getvalue()
    headers = {"Accept-Ranges": "bytes"}
    rentang = re.fullmatch(r"bytes=([0-9]*)-([0-9]*)", request.headers.get("range", ""), re.IGNORECASE)
    if rentang and any(rentang.groups()) and "if-range" not in request.headers:
        awal, akhir = rentang.groups()
        ukuran = len(isi)
        try:
            a = int(awal) if awal else max(0, ukuran - int(akhir))
            b = min(int(akhir), ukuran - 1) if awal and akhir else ukuran - 1
        except ValueError:
            return Response(isi, media_type="audio/wav", headers=headers)
        if a > b:
            headers["Content-Range"] = f"bytes */{ukuran}"
            return Response(status_code=416, headers=headers)
        headers["Content-Range"] = f"bytes {a}-{b}/{ukuran}"
        return Response(isi[a:b + 1], status_code=206, media_type="audio/wav", headers=headers)
    return Response(isi, media_type="audio/wav", headers=headers)


@app.get("/api/kelompok")
def daftar_kelompok() -> list[dict]:
    return [k.ringkasan() for k in kelompok.buat(db.jendela_kelompok())]


class LabelKelompok(BaseModel):
    label: str


@app.post("/api/kelompok/{kid}/label")
def label_kelompok(kid: str, body: LabelKelompok) -> dict:
    label = body.label.strip()
    if not label:
        raise HTTPException(422, "Masukkan label jenis atau label seperti 'bukan katak'.")
    for k in kelompok.buat(db.jendela_kelompok()):
        if k.id == kid:
            n = db.beri_label_kelompok(k.anggota, label)
            return {"diterapkan": n, "label": label}
    raise HTTPException(409, "Kelompok sudah berubah. Muat ulang kelompok lalu dengarkan kembali.")


class Label(BaseModel):
    idx: int
    label: str | None = None


@app.post("/api/rekaman/{rid}/label")
def beri_label(rid: str, body: Label) -> dict:
    _folder(rid)
    db.beri_label(rid, body.idx, body.label)
    return {"ok": True, "label": db.statistik_label()}


@app.post("/api/latih")
def latih() -> dict:
    return db.latih()


@app.get("/api/label.csv")
def ekspor_label():
    _, _, meta = db.data_latih()
    buf = io.StringIO()
    w = csv.DictWriter(buf, fieldnames=["nama_file", "mulai_s", "akhir_s", "label", "rekaman_id", "idx"])
    w.writeheader()
    w.writerows(meta)
    buf.seek(0)
    return StreamingResponse(
        iter([buf.getvalue()]),
        media_type="text/csv",
        headers={"Content-Disposition": "attachment; filename=label_suara_katak.csv"},
    )


@app.get("/api/prediksi.csv")
def ekspor_prediksi():
    buf = io.StringIO()
    fields = ["nama_file", "folder_PAR", "waktu_WIT", "tanggal", "mulai_s", "akhir_s", "label_manual",
              "tebakan_kustom_belum_terverifikasi", "skor_model_tidak_terkalibrasi", "data_latih",
              "model_dilatih_pada", "model_jumlah_label", "model_kelas", "label_berubah",
              "perch_pembanding_tebakan_belum_terverifikasi", "perch_skor_pembanding"]
    w = csv.DictWriter(buf, fieldnames=fields)
    w.writeheader()
    for r in db.daftar_rekaman():
        d = detail(r["id"])
        info = d["model"]
        am = d.get("audiomoth", {})
        for j in d.get("jendela", []):
            custom = next(iter(j.get("model_kustom", [])), {})
            perch_top = next(iter(j.get("perch_umum", [])), {})
            w.writerow(dict(zip(fields, [d["nama_file"], am.get("par"), am.get("waktu"),
                am.get("tanggal"), j["mulai_s"], j["akhir_s"], j.get("label"), custom.get("label"), custom.get("skor"),
                j.get("data_latih", False), info.get("dilatih_pada"), info.get("n"),
                json.dumps(info.get("kelas", {}), ensure_ascii=False), info["usang"],
                perch_top.get("label"), perch_top.get("skor")])))
    return StreamingResponse(iter([buf.getvalue()]), media_type="text/csv",
        headers={"Content-Disposition": "attachment; filename=tebakan_belum_terverifikasi.csv"})


# --- Gaya Arbimon: templat, pencocokan pola, validasi, ringkasan, soundscape -----------------

def _meta() -> dict[str, dict]:
    hasil = {}
    for r in db.daftar_rekaman():
        d = db.ambil_rekaman(r["id"]) or {}
        am = d.get("audiomoth") or {}
        hasil[r["id"]] = {"nama_file": r["nama_file"], "par": am.get("par"), "waktu": am.get("waktu"),
                          "tanggal": am.get("tanggal"), "durasi_s": d.get("durasi_s")}
    return hasil


def _wav(rid: str) -> Path:
    path = _folder(rid) / "terfilter.wav"
    if not path.exists():
        raise HTTPException(404, "Rekaman tidak ditemukan")
    return path


def _png(gambar, simpan_cache: bool = True) -> Response:
    buf = io.BytesIO()
    gambar(buf)
    return Response(buf.getvalue(), media_type="image/png",
                    headers={"Cache-Control": "max-age=3600" if simpan_cache else "no-store"})


def _templat(tid: str) -> dict:
    t = pola.templat(tid) if re.fullmatch(r"[0-9a-f]{12}", tid) else None
    if t is None:
        raise HTTPException(404, "Templat tidak ditemukan")
    return t


@app.get("/api/situs")
def daftar_situs() -> list[dict]:
    jumlah: dict[str, int] = {}
    for m in _meta().values():
        jumlah[m["par"] or ""] = jumlah.get(m["par"] or "", 0) + 1
    return [{"situs": k or None, "rekaman": n} for k, n in sorted(jumlah.items())]


@app.get("/api/rekaman/{rid}/kanvas.png")
def kanvas(rid: str, mulai: float = 0):
    path = _wav(rid)
    return _png(lambda buf: pola_mod.kanvas(path, max(0.0, mulai), buf))


class TemplatBaru(BaseModel):
    rekaman_id: str
    mulai_s: float
    akhir_s: float
    f_min: float
    f_maks: float
    spesies: str
    nama: str = ""


@app.post("/api/templat")
def buat_templat(body: TemplatBaru) -> dict:
    path = _wav(body.rekaman_id)
    nama = (db.ambil_rekaman(body.rekaman_id) or {}).get("nama_file", "")
    try:
        return pola.buat_templat(body.rekaman_id, nama, path, body.mulai_s, body.akhir_s,
                                 body.f_min, body.f_maks, body.spesies, body.nama)
    except InputTidakValid as e:
        raise HTTPException(422, str(e)) from e


@app.get("/api/templat")
def daftar_templat() -> list[dict]:
    return pola.daftar_templat()


@app.delete("/api/templat/{tid}")
def hapus_templat(tid: str) -> dict:
    _templat(tid)
    pola.hapus_templat(tid)
    return {"ok": True}


@app.get("/api/templat/{tid}/gambar.png")
def gambar_templat(tid: str):
    t = _templat(tid)
    patch = pola.patch(tid)
    return _png(lambda buf: pola_mod.gambar(patch, buf, 220, 120,
                                            extent=(0, t["akhir_s"] - t["mulai_s"], t["f_min"], t["f_maks"])))


class Jalankan(BaseModel):
    situs: str | None = None
    ambang: float = 0.5
    maks_per_rekaman: int = 20


@app.post("/api/templat/{tid}/jalankan")
def jalankan_templat(tid: str, body: Jalankan) -> dict:
    _templat(tid)
    target = [(rid, FOLDER_REKAMAN / rid / "terfilter.wav") for rid, m in _meta().items()
              if (not body.situs or m["par"] == body.situs) and (FOLDER_REKAMAN / rid / "terfilter.wav").exists()]
    if not target:
        raise HTTPException(422, "Tidak ada rekaman untuk situs ini.")
    try:
        return pola.jalankan(tid, target, body.ambang, body.maks_per_rekaman)
    except InputTidakValid as e:
        raise HTTPException(422, str(e)) from e


def _cocok_lengkap(rows: list[dict]) -> list[dict]:
    meta = _meta()
    for c in rows:
        m = meta.get(c["rekaman_id"], {})
        c.update({"nama_file": m.get("nama_file"), "situs": m.get("par"), "tanggal": m.get("tanggal"),
                  "waktu_rekaman": m.get("waktu")})
    return rows


@app.get("/api/templat/{tid}/cocok")
def daftar_cocok(tid: str, status: str = "semua") -> list[dict]:
    _templat(tid)
    return _cocok_lengkap(pola.daftar_cocok(tid, status))


@app.get("/api/cocok/{mid}/gambar.png")
def gambar_cocok(mid: int):
    rows = pola.daftar_cocok(mid=mid)
    if not rows:
        raise HTTPException(404)
    c = rows[0]
    path = _wav(c["rekaman_id"])
    return _png(lambda buf: pola_mod.potongan(path, c["mulai_s"], c["akhir_s"], c["f_min"], c["f_maks"], buf))


class Validasi(BaseModel):
    ids: list[int]
    validasi: str | None = None


@app.post("/api/cocok/validasi")
def validasi_cocok(body: Validasi) -> dict:
    try:
        return {"diubah": pola.validasi(body.ids, body.validasi)}
    except InputTidakValid as e:
        raise HTTPException(422, str(e)) from e


@app.get("/api/spesies")
def daftar_spesies() -> list[str]:
    return pola.spesies()


@app.get("/api/ringkasan")
def ringkasan(spesies: str) -> dict:
    return pola.ringkasan(spesies, _meta())


@app.get("/api/cocok.csv")
def ekspor_cocok():
    buf = io.StringIO()
    fields = ["spesies", "templat_id", "situs", "tanggal", "waktu_mulai_rekaman_WIT", "nama_file",
              "mulai_s", "akhir_s", "skor_korelasi", "validasi_manual"]
    w = csv.writer(buf)
    w.writerow(fields)
    for c in _cocok_lengkap(pola.daftar_cocok()):
        w.writerow([c["spesies"], c["templat_id"], c["situs"], c["tanggal"], c["waktu_rekaman"], c["nama_file"],
                    c["mulai_s"], c["akhir_s"], c["skor"], c["validasi"] or "belum divalidasi"])
    return StreamingResponse(iter([buf.getvalue()]), media_type="text/csv",
                             headers={"Content-Disposition": "attachment; filename=kecocokan_pola.csv"})


@app.get("/api/matriks.csv")
def ekspor_matriks(spesies: str):
    r = pola.ringkasan(spesies, _meta())
    kolom = sorted({t for v in r["tanggal"].values() for t in v})
    buf = io.StringIO()
    w = csv.writer(buf)
    w.writerow(["situs", *kolom])
    for situs, per_tgl in sorted(r["tanggal"].items()):
        w.writerow([situs, *[kode_matriks(per_tgl.get(t)) for t in kolom]])
    w.writerow([])
    w.writerow(["# 1 = hadir (validasi manual); 0 = dicari, tanpa kandidat tersisa; "
                "? = kandidat belum divalidasi; NA = tidak dicari"])
    aman = re.sub(r"[^A-Za-z0-9_-]+", "_", spesies)[:60] or "spesies"
    return StreamingResponse(iter([buf.getvalue()]), media_type="text/csv",
                             headers={"Content-Disposition": f"attachment; filename=matriks_deteksi_{aman}.csv"})


def _soundscape(situs: str | None) -> dict:
    rekaman = []
    for rid, m in _meta().items():
        if situs and m["par"] != situs:
            continue
        folder = FOLDER_REKAMAN / rid
        asli = next(folder.glob("asli.*"), None)
        if not asli:
            continue
        try:
            rekaman.append((m["waktu"], soundscape.hitung(asli, folder / "soundscape.json")))
        except Exception:
            logger.exception("Soundscape gagal: %s", rid)
    if not rekaman:
        raise HTTPException(422, "Belum ada rekaman untuk soundscape ini.")
    return soundscape.agregasi(rekaman)


@app.get("/api/soundscape")
def info_soundscape(situs: str | None = None) -> dict:
    h = _soundscape(situs)
    return {k: v for k, v in h.items() if k != "proporsi"}


@app.get("/api/soundscape.png")
def gambar_soundscape(situs: str | None = None):
    h = _soundscape(situs)
    judul = f"Soundscape {situs or 'semua situs'} · {h['rekaman']} rekaman"
    return _png(lambda buf: soundscape.gambar(h, buf, judul), simpan_cache=False)


@app.get("/")
def index():
    return FileResponse(STATIC / "index.html")


app.mount("/static", StaticFiles(directory=STATIC), name="static")
