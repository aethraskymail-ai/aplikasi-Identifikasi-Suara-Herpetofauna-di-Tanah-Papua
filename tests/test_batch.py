import csv

import numpy as np
import pytest
import soundfile as sf

from suarakatak import batch


@pytest.mark.parametrize("sr", [48000, 8000])
def test_csv_senyap_dan_pita_tidak_terukur(tmp_path, sr):
    masukan = tmp_path / "masukan" / "PAR003"
    masukan.mkdir(parents=True)
    sf.write(masukan / "20240101_183000.WAV", np.zeros(sr), sr)
    keluaran = tmp_path / "hasil"
    assert batch.main(["--masukan", str(masukan.parent), "--keluaran", str(keluaran)]) == 0
    with (keluaran / "ringkasan.csv").open(encoding="utf-8", newline="") as f:
        reader = csv.DictReader(f)
        assert reader.fieldnames == batch.KOLOM
        rows = list(reader)
    assert len(rows) == 1
    assert rows[0]["status"] == "ok"
    assert rows[0]["par"] == "PAR003"
    assert float(rows[0]["katak_mean_db_sebelum"]) == -200
    assert float(rows[0]["katak_mean_db_sesudah"]) == -200
    assert rows[0]["jangkrik_mean_db_sebelum"] == ("-200.0" if sr == 48000 else "")
    assert (keluaran / "PAR003" / "2024-01-01" / "20240101_183000.WAV").is_file()
