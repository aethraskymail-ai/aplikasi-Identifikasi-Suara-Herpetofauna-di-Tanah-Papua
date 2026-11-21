import io

import numpy as np
import pytest
import soundfile as sf
from fastapi.testclient import TestClient

from suarakatak import server
from suarakatak.klasifikasi import Penyimpanan


def wav(durasi=1, sr=48000):
    buf = io.BytesIO()
    t = np.arange(int(durasi * sr)) / sr
    sf.write(buf, 0.1 * np.sin(2 * np.pi * 3000 * t), sr, format="WAV")
    return buf.getvalue()


@pytest.fixture
def client(tmp_path, monkeypatch):
    monkeypatch.setattr(server, "FOLDER_REKAMAN", tmp_path / "rekaman")
    monkeypatch.setattr(server, "db", Penyimpanan(tmp_path / "test.sqlite"))
    monkeypatch.setattr(server.perch, "tersedia", lambda: False)
    with TestClient(server.app) as client:
        yield client


def upload(client, data, nama="rekaman.wav"):
    return client.post("/api/analisis", files={"file": (nama, data, "audio/wav")}, data={"perch_terfilter": "false"})


@pytest.mark.parametrize("data,pesan", [
    (b"", "File kosong"),
    (b"bukan audio", "tidak bisa dibaca sebagai audio"),
    (wav(0), "kosong atau rusak"),
    (wav(0.1), "terlalu pendek (0,1 detik); minimal 1 detik"),
    (wav()[:44] + b"garbage", "minimal 1 detik"),
])
def test_audio_tidak_valid_dibersihkan(client, data, pesan):
    response = upload(client, data)
    assert response.status_code == 422
    assert pesan in response.json()["detail"]
    assert "ffmpeg" not in response.text
    assert str(server.FOLDER_REKAMAN) not in response.text
    assert server.db.daftar_rekaman() == []
    assert list(server.FOLDER_REKAMAN.iterdir()) == []


def test_audio_normal_dan_duplikat(client):
    first = upload(client, wav(), "20240101_183000.WAV")
    second = upload(client, wav(), "20240101_183000.WAV")
    assert first.status_code == second.status_code == 200
    data = first.json()
    assert data["durasi_s"] == 1
    assert data["peringatan"] == []
    assert data["audiomoth"]["waktu"] == "2024-01-01 18:30:00"
    assert data["id"] != second.json()["id"]
    assert len(server.db.daftar_rekaman()) == 2


def test_8khz_pita_tidak_terukur(client):
    response = upload(client, wav(sr=8000))
    assert response.status_code == 200
    data = response.json()
    assert "8000 Hz" in data["peringatan"][0]
    assert "4000 Hz" in data["peringatan"][0]
    assert "jangkrik" in data["peringatan"][0]
    for key in ("level_sebelum", "level_sesudah"):
        levels = data["penyaringan"][key]
        assert levels["jangkrik (4300–6600 Hz)"] == {"mean_db": None, "max_db": None}
        assert levels["katak (2400–3800 Hz)"]["mean_db"] is not None


def test_error_tak_terduga_tidak_bocor(client, monkeypatch, caplog):
    def gagal(path, folder, rid, nama, terfilter, path_relatif=""):
        server.db.simpan_rekaman(rid, nama, {}, [])
        raise RuntimeError("rahasia /internal/path command")

    monkeypatch.setattr(server, "_proses", gagal)
    response = upload(client, wav())
    assert response.status_code == 500
    assert "gangguan server" in response.json()["detail"]
    assert "rahasia" not in response.text
    assert "rahasia /internal/path command" in caplog.text
    assert server.db.daftar_rekaman() == []
    assert list(server.FOLDER_REKAMAN.iterdir()) == []


def test_perch_gagal_tidak_bocor(client, monkeypatch):
    def gagal(*args):
        raise RuntimeError("rahasia /model/path")

    monkeypatch.setattr(server.perch, "tersedia", lambda: True)
    monkeypatch.setattr(server.perch, "analisis", gagal)
    response = upload(client, wav())
    assert response.status_code == 200
    assert "rahasia" not in response.text
    assert "belum bisa digunakan" in response.json()["catatan_perch"]


def test_ekstensi_tidak_didukung(client):
    response = upload(client, b"dokumen", "dokumen.pdf")
    assert response.status_code == 400
    assert "belum didukung" in response.json()["detail"]
    assert server.db.daftar_rekaman() == []


@pytest.mark.parametrize("rusak,status", [(True, 422), (False, 500)])
def test_pembersihan_db_gagal_folder_tetap_dihapus(client, monkeypatch, caplog, rusak, status):
    def gagal_hapus(rid):
        raise RuntimeError("SQLite hanya baca")

    def gagal_proses(*args):
        raise RuntimeError("kesalahan internal")

    monkeypatch.setattr(server.db, "hapus_rekaman", gagal_hapus)
    if not rusak:
        monkeypatch.setattr(server, "_proses", gagal_proses)
    response = upload(client, b"" if rusak else wav())
    assert response.status_code == status
    assert "SQLite" not in response.text
    assert "Pembersihan basis data gagal" in caplog.text
    assert list(server.FOLDER_REKAMAN.iterdir()) == []


@pytest.mark.parametrize("path_relatif,par", [
    ("PAR003/20240101_183000.WAV", "PAR003"),
    ("../../PAR003/20240101_183000.WAV", "PAR003"),
    ("../20240101_183000.WAV", None),
    ("", None),
])
def test_path_folder_hanya_metadata(client, path_relatif, par):
    response = client.post("/api/analisis", files={"file": ("20240101_183000.WAV", wav(), "audio/wav")},
                           data={"perch_terfilter": "false", "path_relatif": path_relatif})
    assert response.status_code == 200
    data = response.json()
    assert data["nama_file"] == "20240101_183000.WAV"
    assert data["audiomoth"]["par"] == par
    assert data["audiomoth"]["waktu"] == "2024-01-01 18:30:00"
    assert (server.FOLDER_REKAMAN / data["id"] / "asli.wav").is_file()
    assert len(list(server.FOLDER_REKAMAN.iterdir())) == 1
