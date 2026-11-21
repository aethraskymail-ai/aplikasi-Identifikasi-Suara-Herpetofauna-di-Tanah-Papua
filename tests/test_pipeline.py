import numpy as np
import pytest

from suarakatak import contoh, deteksi, pipeline
from suarakatak.audio import info_nama_file
from suarakatak.klasifikasi import Penyimpanan
from types import SimpleNamespace
import csv
import io


def penyimpanan(tmp_path, recordings=1):
    db = Penyimpanan(tmp_path / "test.sqlite")
    for r in range(recordings):
        rid = f"{r:012x}"
        windows = [SimpleNamespace(mulai_s=i*5, akhir_s=(i+1)*5,
                   embedding=np.array([i % 2, r, i], dtype=np.float32)) for i in range(4)]
        summary = {"nama_file": "PAR001/test.wav", "audiomoth": {"par": "PAR001", "waktu": "2026-01-01"},
                   "jendela": [{"idx": i, "mulai_s": i*5, "akhir_s": (i+1)*5,
                                "perch_umum": [{"label": "pembanding", "skor": .5}]} for i in range(4)]}
        db.simpan_rekaman(rid, summary["nama_file"], summary, windows)
        for i in range(4):
            db.beri_label(rid, i, "katak" if i % 2 else "bukan katak")
    return db


def test_prediksi_tidak_melatih_dan_model_persisten(tmp_path, monkeypatch):
    db = penyimpanan(tmp_path)
    monkeypatch.setattr(db, "latih", lambda: (_ for _ in ()).throw(AssertionError("auto-training")))
    assert db.prediksi(db.embedding_rekaman("000000000000")) == [[], [], [], []]
    assert not db.info_model()["siap"]
    monkeypatch.undo()
    info = db.latih()
    assert info["akurasi_cv"] is None
    assert "antarrekaman" in info["pesan"] and info["data_kecil"]
    restored = Penyimpanan(db.path)
    assert restored.info_model()["dilatih_pada"] == info["dilatih_pada"]
    assert restored.prediksi(np.zeros((0, 3))) == []
    assert restored.prediksi(db.embedding_rekaman("000000000000"))


def test_label_berubah_dan_keanggotaan_latih(tmp_path):
    db = penyimpanan(tmp_path)
    db.latih()
    assert not db.info_model()["usang"]
    db.beri_label("000000000000", 0, "baru")
    assert db.info_model()["usang"]
    assert db.data_latih_model("000000000000", 0)
    db.beri_label("000000000000", 0, "bukan katak")
    assert not db.info_model()["usang"]
    db.beri_label("000000000000", 0, None)
    assert db.info_model()["usang"]
    db.beri_label("000000000000", 0, "bukan katak")
    db.hapus_rekaman("000000000000")
    assert db.info_model()["usang"]
    assert db.latih()["siap"] is False
    assert db.model() is not None  # gagal melatih tidak mengganti model terakhir


def test_cv_dikelompokkan_per_rekaman(tmp_path, monkeypatch):
    db = penyimpanan(tmp_path, recordings=3)
    import sklearn.model_selection
    def check(model, x, y, cv):
        _, _, meta = db.data_latih()
        for train, test in cv:
            assert {meta[i]["rekaman_id"] for i in train}.isdisjoint(
                {meta[i]["rekaman_id"] for i in test})
        return np.array([.5] * len(cv))
    monkeypatch.setattr(sklearn.model_selection, "cross_val_score", check)
    assert db.latih()["akurasi_cv"] == .5


def test_prediksi_csv_endpoint(tmp_path, monkeypatch):
    from fastapi.testclient import TestClient
    from suarakatak import server
    db = penyimpanan(tmp_path)
    monkeypatch.setattr(server, "db", db)
    client = TestClient(server.app)
    rows = list(csv.DictReader(io.StringIO(client.get("/api/prediksi.csv").text)))
    assert len(rows) == 4 and rows[0]["tebakan_kustom_belum_terverifikasi"] == ""
    db.latih()
    response = client.get("/api/prediksi.csv")
    assert response.status_code == 200
    rows = list(csv.DictReader(io.StringIO(response.text)))
    assert rows[0]["data_latih"] == "True"
    assert rows[0]["model_jumlah_label"] == "4"
    assert rows[0]["model_dilatih_pada"]
    assert rows[0]["folder_PAR"] == "PAR001"
    assert rows[0]["perch_pembanding_tebakan_belum_terverifikasi"] == "pembanding"
    assert rows[0]["tebakan_kustom_belum_terverifikasi"]
    assert client.get("/api/rekaman/tidak-ada").status_code == 404
    db.hapus_rekaman("000000000000")
    assert list(csv.DictReader(io.StringIO(client.get("/api/prediksi.csv").text))) == []


def test_nama_file_audiomoth():
    info = info_nama_file("I:/PAR/PAR001/20260429_183000.WAV")
    assert info.par == "PAR001"
    assert info.waktu.hour == 18 and info.dalam_jendela
    assert info_nama_file("PAR002/20260429_120000.WAV").dalam_jendela is False
    assert info_nama_file("rekaman.wav").waktu is None


def test_aktivitas_panggilan_memenuhi_rekaman_pendek():
    sr = 48000
    t = np.arange(int(sr * 2.5)) / sr
    noise = np.random.default_rng(12).normal(0, 0.001, len(t))
    call = 0.1 * np.sin(2 * np.pi * 3000 * t) * ((t >= 0.1) & (t < 2.3))
    segmen = deteksi.segmen_aktif(noise + call, sr)
    assert deteksi.ringkas_aktivitas(segmen, 2.5)["persen_aktif"] >= 80
    assert deteksi.segmen_aktif(noise, sr) == []
    assert deteksi.segmen_aktif(np.zeros_like(t), sr) == []


def test_mode_rendah_mempertahankan_panggilan_800_hz():
    sr = 48000
    t = np.arange(sr * 4) / sr
    x = (0.1 * np.sin(2 * np.pi * 800 * t) * ((t % 0.8) < 0.4)).astype(np.float32)
    standar = pipeline.jalankan(x, sr)
    eksplisit = pipeline.jalankan(x, sr, mode_rendah=False)
    rendah = pipeline.jalankan(x, sr, mode_rendah=True)
    np.testing.assert_array_equal(standar.audio, eksplisit.audio)
    assert pipeline.HIGHPASS_HZ == 2100
    assert pipeline.PITA_KATAK == (2400, 3800)
    assert not any(500 <= p.frekuensi_hz <= 3800 for p in rendah.puncak)
    level = lambda y: pipeline.level_pita(y, sr, (750, 850))["mean_db"]
    mentah = lambda h: h.audio / 10 ** (h.gain_db / 20)
    assert abs(level(mentah(rendah)) - level(x)) < 3
    assert level(mentah(standar)) < level(x) - 25
    assert deteksi.segmen_aktif(rendah.audio, sr, pita=pipeline.PITA_RENDAH)


def test_pipeline_meredam_gangguan_dan_menjaga_pita_katak():
    x = contoh.buat(durasi_s=20)
    h = pipeline.jalankan(x, contoh.SR)
    f = sorted(p.frekuensi_hz for p in h.puncak)
    for target in (1000, 1330, 1550, 4492, 5133):
        assert any(abs(fi - target) < 6 for fi in f), target
    assert not any(2400 <= fi <= 3800 for fi in f)
    sebelum, sesudah = h.level_sebelum, h.level_sesudah
    assert sesudah["dengung (900–1900 Hz)"]["mean_db"] < sebelum["dengung (900–1900 Hz)"]["mean_db"] - 40
    assert sesudah["jangkrik (4300–6600 Hz)"]["mean_db"] < sebelum["jangkrik (4300–6600 Hz)"]["mean_db"] - 10
    katak = "katak (2400–3800 Hz)"
    assert abs(sesudah[katak]["mean_db"] - sebelum[katak]["mean_db"]) < 3
    assert abs(pipeline.max_volume_db(h.audio) - pipeline.TARGET_PUNCAK_DB) < 0.05
    assert h.sr == 48000


def test_deteksi_menemukan_panggilan():
    x = contoh.buat(durasi_s=20)
    h = pipeline.jalankan(x, contoh.SR)
    seg = deteksi.segmen_aktif(h.audio, h.sr)
    assert 2 <= len(seg) <= 6
    assert all(s["snr_db"] > 10 for s in seg)


def test_equalizer_notch_tepat_di_frekuensi():
    sr = 48000
    t = np.arange(sr) / sr
    x = np.sin(2 * np.pi * 1500 * t).astype(np.float32)
    y = pipeline.notch_bertingkat(x, sr, [pipeline.Puncak(1500.0, 30, -10)])
    assert pipeline.max_volume_db(y[sr // 2 :]) < -60


@pytest.mark.parametrize("frekuensi", [1500, 2150])
def test_notch_hanya_nada_persisten(monkeypatch, frekuensi):
    monkeypatch.setattr(pipeline, "JARAK_AMAN_PITA_HZ", 60.0)
    sr = 48000
    t = np.arange(sr * 6) / sr
    noise = 0.002 * np.random.default_rng(42).standard_normal(len(t))
    nada = 0.1 * np.sin(2 * np.pi * frekuensi * t)
    pulsa = noise + nada * ((t % 0.55) < 0.3)
    kontinu = noise + nada
    p_pulsa = pipeline.cari_puncak_gangguan(pulsa, sr)
    p_kontinu = pipeline.cari_puncak_gangguan(kontinu, sr)
    assert not any(abs(p.frekuensi_hz - frekuensi) < 20 for p in p_pulsa)
    assert any(abs(p.frekuensi_hz - frekuensi) < 6 for p in p_kontinu)
    pita = (frekuensi - 20, frekuensi + 20)
    y_pulsa = pipeline.notch_bertingkat(pulsa, sr, p_pulsa)
    y_kontinu = pipeline.notch_bertingkat(kontinu, sr, p_kontinu)
    level = lambda x: pipeline.level_pita(x[sr:], sr, pita)["mean_db"]
    assert abs(level(y_pulsa) - level(pulsa)) < 1
    assert level(y_kontinu) < level(kontinu) - 30


@pytest.mark.parametrize("durasi", [0, 0.1, 1])
def test_notch_tanpa_bukti_nada(durasi):
    assert pipeline.cari_puncak_gangguan(np.zeros(int(48000 * durasi)), 48000) == []


@pytest.mark.parametrize("amplitudo,senyap", [(0, True), (1e-8, True), (0.1, False)])
def test_level_pita_senyap_tetap_numerik(amplitudo, senyap):
    sr = 48000
    t = np.arange(sr) / sr
    level = pipeline.level_pita(amplitudo * np.sin(2 * np.pi * 3000 * t), sr, pipeline.PITA_KATAK)
    assert level["senyap"] is senyap
    assert np.isfinite(level["mean_db"])
    assert np.isfinite(level["max_db"])


def test_pita_tidak_terukur_bukan_senyap():
    level = pipeline.level_pita(np.zeros(8000), 8000, (4300, 6600))
    assert level == {"mean_db": None, "max_db": None}


def test_notch_dekat_tepi_tidak_memotong_pita_katak():
    from suarakatak.pipeline import level_pita

    sr = 48000
    t = np.arange(sr * 4) / sr
    x = (0.3 * np.sin(2 * np.pi * 3900 * t) + 0.05 * np.sin(2 * np.pi * 3780 * t)).astype(np.float32)
    puncak = pipeline.cari_puncak_gangguan(x, sr)
    y = pipeline.notch_bertingkat(x, sr, puncak)
    pita = (3760.0, 3800.0)
    assert abs(level_pita(y, sr, pita)["mean_db"] - level_pita(x, sr, pita)["mean_db"]) < 1.5


def test_rekaman_44100_dikeluarkan_48000():
    x = contoh.buat(durasi_s=3.0)
    from suarakatak.audio import resample

    h = pipeline.jalankan(resample(x, 48000, 44100), 44100)
    assert h.sr == 48000


def test_rekaman_8khz_keluaran_48khz_tidak_menambah_pita_terukur():
    sr = 8000
    t = np.arange(sr) / sr
    h = pipeline.jalankan((0.1 * np.sin(2 * np.pi * 3000 * t)).astype(np.float32), sr)
    assert h.sr == 48000
    for level in (h.level_sebelum, h.level_sesudah):
        assert level["jangkrik (4300–6600 Hz)"] == {"mean_db": None, "max_db": None}
        assert level["katak (2400–3800 Hz)"]["mean_db"] is not None
