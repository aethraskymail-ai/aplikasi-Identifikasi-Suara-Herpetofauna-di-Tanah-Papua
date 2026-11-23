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
    sf.write(buf, 0.1 * np.sin(2 * np.pi * 3000 * t) * ((t % 0.5) < 0.25), sr, format="WAV")
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


def test_rekaman_harian(client):
    response = upload(client, wav(), "PAR002_2026-05-06.mp3")
    assert response.status_code == 200
    data = response.json()
    assert data["audiomoth"] == {"par": "PAR002", "tanggal": "2026-05-06", "waktu": None,
                                 "dalam_jendela_1730_2100": None}
    assert "jam mulai tidak diketahui" in data["peringatan"][0]


def test_error_tak_terduga_tidak_bocor(client, monkeypatch, caplog):
    def gagal(path, folder, rid, nama, perch_terfilter, path_relatif="", mode_rendah=False):
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

    def gagal_proses(*args, **kwargs):
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


@pytest.mark.parametrize("mode_rendah", [False, True])
def test_mode_dan_folder_diteruskan_bersama(client, mode_rendah):
    response = client.post(
        "/api/analisis", files={"file": ("20240101_183000.WAV", wav(), "audio/wav")},
        data={"mode_rendah": str(mode_rendah).lower(),
              "path_relatif": "PAR007/20240101_183000.WAV"})
    assert response.status_code == 200
    data = response.json()
    assert data["mode_rendah"] is mode_rendah
    assert data["pita_aktivitas_hz"] == ([500, 3800] if mode_rendah else [2400, 3800])
    assert data["audiomoth"]["par"] == "PAR007"
    assert data["peringatan"] == []
    stored = client.get(f'/api/rekaman/{data["id"]}').json()
    assert stored["mode_rendah"] is mode_rendah


def test_kelompok_perch_audio_label_dan_latih(client, monkeypatch):
    assert client.get("/api/kelompok").json() == []

    def jendela_contoh(x, sr):
        mata = np.eye(2, dtype=np.float32)
        return [server.perch.Jendela(i * 5, (i + 1) * 5, mata[i % 2], np.zeros(2)) for i in range(4)]

    monkeypatch.setattr(server.perch, "tersedia", lambda: True)
    monkeypatch.setattr(server.perch, "analisis", jendela_contoh)
    monkeypatch.setattr(server.perch, "teratas", lambda *a, **kw: [])
    id_a = upload(client, wav(20), "PAR001_2026-04-29.mp3").json()["id"]
    id_b = upload(client, wav(20), "PAR002_2026-05-06.mp3").json()["id"]
    assert client.post(f"/api/rekaman/{id_a}/label", json={"idx": 0, "label": "bukan katak"}).is_success

    hasil = client.get("/api/kelompok").json()
    assert sorted(k["jumlah"] for k in hasil) == [4, 4]
    assert sorted(k["belum_dilabel"] for k in hasil) == [3, 4]
    for k in hasil:
        assert len(k["contoh"]) == 3
        assert len({j["idx"] % 2 for j in k["contoh"]}) == 1
        assert all("embedding" not in j for j in k["contoh"])

    tautan = f"/api/rekaman/{id_b}/jendela/1/audio.wav"
    audio = client.get(tautan)
    assert audio.is_success
    assert audio.headers["content-type"] == "audio/wav"
    assert audio.headers["accept-ranges"] == "bytes"
    parsial = client.get(tautan, headers={"Range": "bytes=0-1"})
    assert parsial.status_code == 206
    assert parsial.headers["content-range"] == f"bytes 0-1/{len(audio.content)}"
    assert parsial.headers["accept-ranges"] == "bytes"
    assert parsial.content == audio.content[:2]
    assert client.get(tautan, headers={"Range": "bytes=-8"}).content == audio.content[-8:]
    di_luar = client.get(tautan, headers={"Range": f"bytes={len(audio.content)}-"})
    assert di_luar.status_code == 416
    assert di_luar.headers["content-range"] == f"bytes */{len(audio.content)}"
    clip, sr = sf.read(io.BytesIO(audio.content), dtype="int16")
    with sf.SoundFile(server.FOLDER_REKAMAN / id_b / "terfilter.wav") as sumber:
        sumber.seek(5 * sr)
        assert len(clip) == 5 * sr
        np.testing.assert_array_equal(clip, sumber.read(5 * sr, dtype="int16"))
    assert client.get(f"/api/rekaman/{id_b}/jendela/99/audio.wav").status_code == 404

    kelompok_a, kelompok_b = sorted(hasil, key=lambda k: k["belum_dilabel"])
    url_a = f"/api/kelompok/{kelompok_a['id']}/label"
    assert client.post(url_a, json={"label": "  "}).status_code == 422
    assert client.post("/api/kelompok/kedaluwarsa/label", json={"label": "hujan"}).status_code == 409
    assert client.post(url_a, json={"label": " bukan katak "}).json() == {"label": "bukan katak", "diterapkan": 3}
    assert client.post(url_a, json={"label": "hujan"}).json()["diterapkan"] == 0
    assert client.post("/api/latih").json()["siap"] is False
    assert client.post(f"/api/kelompok/{kelompok_b['id']}/label", json={"label": "hujan"}).json()["diterapkan"] == 4

    latihan = client.post("/api/latih").json()
    assert latihan["siap"] is True
    assert latihan["kelas"] == {"bukan katak": 4, "hujan": 4}
    detail = client.get(f"/api/rekaman/{id_a}").json()
    assert detail["jendela"][0]["label"] == "bukan katak"
    assert detail["jendela"][1]["label"] == "hujan"
    assert all(j["data_latih"] and j["model_kustom"] for j in detail["jendela"])
    assert len(client.get("/api/label.csv").text.splitlines()) == 9
