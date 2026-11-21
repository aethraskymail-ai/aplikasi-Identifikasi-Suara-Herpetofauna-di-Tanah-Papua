"""Server web: `uvicorn suarakatak.server:app --port 8000`."""

from __future__ import annotations

import csv
import io
import logging
import os
import re
import shutil
import uuid
from pathlib import Path

from fastapi import FastAPI, File, Form, HTTPException, UploadFile
from fastapi.responses import FileResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from . import __version__, contoh, perch
from .analisis import analisis_file
from .audio import AudioTidakValid, simpan_wav
from .klasifikasi import Penyimpanan

DATA_DIR = Path(os.environ.get("SUARAKATAK_DATA", Path.home() / ".suarakatak")).expanduser()
FOLDER_REKAMAN = DATA_DIR / "rekaman"
STATIC = Path(__file__).parent / "static"
EKSTENSI = {".wav", ".flac", ".mp3", ".m4a", ".ogg", ".aac", ".mpga"}
logger = logging.getLogger(__name__)

app = FastAPI(title="Identifikasi Suara Herpetofauna Tanah Papua", version=__version__)
db = Penyimpanan(DATA_DIR / "suarakatak.sqlite")


def _folder(rid: str) -> Path:
    if not re.fullmatch(r"[0-9a-f]{12}", rid):
        raise HTTPException(404)
    return FOLDER_REKAMAN / rid


def _proses(path_asli: Path, folder: Path, rid: str, nama: str, perch_terfilter: bool) -> dict:
    ringkasan, jendela = analisis_file(path_asli, folder, nama, perch_terfilter)
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
    }


@app.post("/api/analisis")
def analisis(file: UploadFile = File(...), perch_terfilter: bool = Form(False)) -> dict:
    nama = Path(file.filename or "rekaman.wav").name
    ext = Path(nama).suffix.lower()
    if ext not in EKSTENSI:
        raise HTTPException(400, f"Format {ext or '?'} belum didukung. Pakai WAV/FLAC/MP3/M4A/OGG.")
    rid = uuid.uuid4().hex[:12]
    folder = FOLDER_REKAMAN / rid
    path_asli = folder / f"asli{ext}"
    try:
        folder.mkdir(parents=True)
        with open(path_asli, "wb") as f:
            shutil.copyfileobj(file.file, f)
        if not path_asli.stat().st_size:
            raise AudioTidakValid("File kosong. Coba salin ulang dari kartu AudioMoth.")
        return _proses(path_asli, folder, rid, nama, perch_terfilter)
    except Exception as e:
        logger.exception("Analisis unggahan gagal: %s", rid)
        try:
            db.hapus_rekaman(rid)
        except Exception:
            logger.exception("Pembersihan basis data gagal: %s", rid)
        shutil.rmtree(folder, ignore_errors=True)
        if isinstance(e, AudioTidakValid):
            raise HTTPException(422, f"{nama}: {e}") from e
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
    data["model_kustom_aktif"] = db.model() is not None
    return data


@app.delete("/api/rekaman/{rid}")
def hapus(rid: str) -> dict:
    folder = _folder(rid)
    db.hapus_rekaman(rid)
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


@app.get("/")
def index():
    return FileResponse(STATIC / "index.html")


app.mount("/static", StaticFiles(directory=STATIC), name="static")
