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
