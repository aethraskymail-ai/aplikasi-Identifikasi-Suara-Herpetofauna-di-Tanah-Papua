import numpy as np

from suarakatak import analisis


def test_spektrogram_skala_gain_dan_sumbu(monkeypatch, tmp_path):
    import matplotlib

    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    sr = 48000
    x = np.random.default_rng(7).normal(0, 0.01, sr)
    figures = []
    monkeypatch.setattr(plt, "close", lambda fig: figures.append(fig))
    try:
        analisis.gambar_spektrogram(x, sr, tmp_path / "sebelum.png", "Sebelum")
        analisis.gambar_spektrogram(x * 2, sr, tmp_path / "sesudah.png", "Sesudah",
                                   gain_db=20 * np.log10(2))
        a, b = [fig.axes[0] for fig in figures if hasattr(fig, "axes")]
        np.testing.assert_allclose(a.images[0].get_array(), b.images[0].get_array())
        assert a.images[0].get_clim() == b.images[0].get_clim() == analisis.SKALA_SPEKTROGRAM_DB
        assert a.get_ylim() == b.get_ylim() == (0, 12000)
        assert a.get_xlabel() == "detik"
        assert a.get_ylabel() == "Hz"
        assert a.figure.axes[1].get_ylabel() == "Level (dB)"
        short_width = a.figure.get_figwidth()
        analisis.gambar_spektrogram(np.tile(x, 31), sr, tmp_path / "panjang.png", "Panjang")
        assert figures[-1].get_figwidth() > short_width
    finally:
        monkeypatch.undo()
        plt.close("all")
