import numpy as np
import pytest
from fastapi.testclient import TestClient

from suarakatak import contoh, pipeline, pola, server, soundscape
from suarakatak.audio import simpan_wav
from suarakatak.klasifikasi import Penyimpanan


@pytest.fixture
def client(tmp_path, monkeypatch):
    path = tmp_path / "test.sqlite"
    monkeypatch.setattr(server, "FOLDER_REKAMAN", tmp_path / "rekaman")
    monkeypatch.setattr(server, "db", Penyimpanan(path))
    monkeypatch.setattr(server, "pola", pola.Pola(path))
    monkeypatch.setattr(server.perch, "tersedia", lambda: False)
    with TestClient(server.app) as client:
        yield client


def test_korelasi_geser_menemukan_pola_dan_skala_tidak_berpengaruh():
    rng = np.random.default_rng(0)
    s = rng.normal(size=(8, 200))
    t = s[:, 50:70].copy()
    r = pola.korelasi_geser(s * 3 + 10, t)
    assert int(np.argmax(r)) == 50
    assert r[50] == pytest.approx(1.0, abs=1e-5)
    assert r.max() <= 1


def test_cari_cocok_contoh_sintetis(tmp_path):
    h = pipeline.jalankan(contoh.buat(), contoh.SR)
    path = tmp_path / "t.wav"
    simpan_wav(path, h.audio, h.sr)
    patch = pola.ambil_patch(path, 1.98, 2.75, 2700, 3200)
    hasil = pola.cari_cocok(path, patch, 2700, 3200, 0.5, 50)
    mulai = [m for m, _ in hasil]
    assert len(hasil) >= 8
    assert all(skor >= 0.5 for _, skor in hasil)
    assert min(abs(m - 1.98) for m in mulai) < 0.02
    assert all(b - a >= 0.77 - 1e-6 for a, b in zip(mulai, mulai[1:]))


def test_cari_cocok_lintas_blok(tmp_path, monkeypatch):
    monkeypatch.setattr(pola, "BLOK_S", 7.0)
    h = pipeline.jalankan(contoh.buat(), contoh.SR)
    path = tmp_path / "t.wav"
    simpan_wav(path, h.audio, h.sr)
    patch = pola.ambil_patch(path, 1.98, 2.75, 2700, 3200)
    monkeypatch.setattr(pola, "BLOK_S", 300.0)
    penuh = pola.cari_cocok(path, patch, 2700, 3200, 0.5, 50)
    monkeypatch.setattr(pola, "BLOK_S", 7.0)
    blok = pola.cari_cocok(path, patch, 2700, 3200, 0.5, 50)
    assert [m for m, _ in blok] == pytest.approx([m for m, _ in penuh], abs=0.01)


def test_soundscape_puncak_dan_agregasi():
    sr = 48000
    t = np.arange(sr * 2) / sr
    x = 0.001 * np.random.default_rng(1).normal(size=len(t)) + 0.1 * np.sin(2 * np.pi * 3000 * t)
    b = soundscape.puncak_segmen(x, sr)
    assert int(3000 // soundscape.BIN_HZ) in b
    h = soundscape.agregasi([("2026-04-29T18:30:00", [{"offset_s": 0, "bin": b}]), (None, [{"offset_s": 0, "bin": []}])])
    assert h["sumbu"] == "jam WIT" and h["rekaman_tanpa_jam_dilewati"] == 1
    assert h["proporsi"][int(3000 // soundscape.BIN_HZ), 18] == 1
    harian = soundscape.agregasi([(None, [{"offset_s": 3700, "bin": b}])])
    assert harian["sumbu"] == "jam sejak awal rekaman" and harian["proporsi"].shape[1] == 2


def test_alur_arbimon_api(client):
    a = client.post("/api/contoh").json()
    b = client.post("/api/contoh").json()
    assert client.post("/api/templat", json={"rekaman_id": a["id"], "mulai_s": 1.98, "akhir_s": 1.99,
                                             "f_min": 2700, "f_maks": 3200, "spesies": "x"}).status_code == 422
    assert client.post("/api/templat", json={"rekaman_id": a["id"], "mulai_s": 1.98, "akhir_s": 2.75,
                                             "f_min": 2700, "f_maks": 3200, "spesies": " "}).status_code == 422
    t = client.post("/api/templat", json={"rekaman_id": a["id"], "mulai_s": 1.98, "akhir_s": 2.75,
                                          "f_min": 2700, "f_maks": 3200, "spesies": "Litoria sp."}).json()
    assert client.get(f"/api/templat/{t['id']}/gambar.png").headers["content-type"] == "image/png"
    assert client.get(f"/api/rekaman/{a['id']}/kanvas.png").status_code == 200
    assert client.get("/api/situs").json() == [{"situs": "PAR001", "rekaman": 2}]

    r = client.post(f"/api/templat/{t['id']}/jalankan", json={"situs": "PAR001", "ambang": 0.5}).json()
    assert r["rekaman_dicari"] == 2 and r["kandidat_baru"] >= 16
    rk = client.get("/api/ringkasan", params={"spesies": "Litoria sp."}).json()
    assert rk["rekaman_hadir"] == 0 and rk["rekaman_belum_divalidasi"] == 2
    assert rk["jam"]["PAR001"]["18"] == {"rekaman": 2, "hadir": 0, "belum": 2}

    cocok = client.get(f"/api/templat/{t['id']}/cocok").json()
    assert client.get(f"/api/cocok/{cocok[0]['id']}/gambar.png").status_code == 200
    di_a = [c["id"] for c in cocok if c["rekaman_id"] == a["id"]]
    di_b = [c["id"] for c in cocok if c["rekaman_id"] == b["id"]]
    assert client.post("/api/cocok/validasi", json={"ids": di_a[:1], "validasi": "mungkin"}).status_code == 422
    client.post("/api/cocok/validasi", json={"ids": di_a[:1], "validasi": "hadir"})
    client.post("/api/cocok/validasi", json={"ids": di_b, "validasi": "tidak"})
    rk = client.get("/api/ringkasan", params={"spesies": "Litoria sp."}).json()
    assert rk["rekaman_hadir"] == 1 and rk["rekaman_belum_divalidasi"] == 0
    assert rk["situs_hadir"] == 1 and rk["okupansi_naif"] == 1
    assert client.get(f"/api/rekaman/{a['id']}").json()["hadir_tervalidasi"] == [{"spesies": "Litoria sp.", "n": 1}]
    assert client.get(f"/api/rekaman/{b['id']}").json()["hadir_tervalidasi"] == []

    # menjalankan ulang tidak menghapus atau menggandakan kecocokan yang sudah divalidasi
    client.post(f"/api/templat/{t['id']}/jalankan", json={"ambang": 0.5})
    ulang = client.get(f"/api/templat/{t['id']}/cocok").json()
    assert len(ulang) == len(cocok)
    assert sum(c["validasi"] == "tidak" for c in ulang) == len(di_b)

    matriks = client.get("/api/matriks.csv", params={"spesies": "Litoria sp."}).text.splitlines()
    assert matriks[:2] == ["situs,2026-04-29", "PAR001,1"]
    assert "belum divalidasi" in client.get("/api/cocok.csv").text
    assert client.get("/api/soundscape").json()["sumbu"] == "jam WIT"
    assert client.get("/api/soundscape.png", params={"situs": "PAR001"}).headers["content-type"] == "image/png"

    client.delete(f"/api/rekaman/{b['id']}")
    assert all(c["rekaman_id"] == a["id"] for c in client.get(f"/api/templat/{t['id']}/cocok").json())
    client.delete(f"/api/templat/{t['id']}")
    assert client.get("/api/templat").json() == []
