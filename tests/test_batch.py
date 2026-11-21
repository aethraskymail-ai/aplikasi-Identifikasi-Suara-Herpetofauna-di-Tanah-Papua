import csv
from datetime import time
import shutil
import subprocess

import numpy as np
import pytest
import soundfile as sf

from suarakatak import batch


def test_pilih_mp3_harian(tmp_path):
    for nama in ["PAR001_2026-05-06.mp3", "PAR001_2026-02-30.mp3", "unknown.mp3",
                 "PAR001_2026-05-07.mp3.part", "20260506_090000.WAV", "20260506_183000.WAV"]:
        (tmp_path / nama).touch()
    hasil = list(batch.cari_file(tmp_path, time(17, 30), time(21)))
    assert [p.name for p, _ in hasil] == ["20260506_183000.WAV", "PAR001_2026-05-06.mp3"]


@pytest.mark.skipif(not shutil.which("ffmpeg"), reason="ffmpeg diperlukan untuk membuat MP3")
def test_batch_mp3_harian(tmp_path):
    source = tmp_path / "source.wav"
    sf.write(source, np.zeros(48000), 48000)
    masukan = tmp_path / "masukan"
    masukan.mkdir()
    nama = "PAR024_PAR015_2026-05-13.mp3"
    subprocess.run(["ffmpeg", "-v", "error", "-i", str(source), str(masukan / nama)], check=True)
    keluaran = tmp_path / "hasil"
    assert batch.main(["--masukan", str(masukan), "--keluaran", str(keluaran)]) == 0
    with (keluaran / "ringkasan.csv").open() as f:
        row = next(csv.DictReader(f))
    assert row["status"] == "ok"
    assert row["waktu"] == ""
    assert row["tanggal"] == "2026-05-13"
    assert row["par"] == "PAR024_PAR015"
    assert (keluaran / "PAR024_PAR015" / "2026-05-13" / nama.replace(".mp3", ".WAV")).exists()


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
