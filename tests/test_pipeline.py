import numpy as np
import pytest

from suarakatak import contoh, deteksi, pipeline
from suarakatak.audio import info_nama_file


def test_nama_file_audiomoth():
    info = info_nama_file("I:/PAR/PAR001/20260429_183000.WAV")
    assert info.par == "PAR001"
    assert info.waktu.hour == 18 and info.dalam_jendela
    assert info_nama_file("PAR002/20260429_120000.WAV").dalam_jendela is False
    assert info_nama_file("rekaman.wav").waktu is None


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
