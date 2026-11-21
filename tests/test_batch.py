import csv
from types import SimpleNamespace

import numpy as np
import pytest
import soundfile as sf

from suarakatak import batch, perch


@pytest.fixture
def drive(tmp_path):
    source = tmp_path / "drive" / "PAR001"
    source.mkdir(parents=True)
    path = source / "20261118_173000.WAV"
    t = np.arange(48000) / 48000
    sf.write(path, .2 * np.sin(2 * np.pi * 2940 * t), 48000, subtype="PCM_16")
    (source / "CONFIG.TXT").write_text("Sample rate: 48000 Hz\nTime zone: UTC+9\n")
    out = tmp_path / "out"
    return source.parent, path, out


def run(drive, *extra):
    source, _, out = drive
    return batch.main(["--masukan", str(source), "--keluaran", str(out), *extra])


def rows(out):
    with (out / "ringkasan.csv").open(newline="", encoding="utf-8") as f:
        return list(csv.DictReader(f))


def wav(out):
    return out / "PAR001/2026-11-18/20261118_173000.WAV"


def embedding(out):
    return out / "embedding/PAR001/20261118_173000.npz"


@pytest.fixture
def mock_perch(monkeypatch):
    calls = []

    def analisis(x, sr):
        calls.append((x.copy(), sr))
        return [SimpleNamespace(embedding=np.zeros(1536), logit=np.ones(2), mulai_s=0)]

    monkeypatch.setattr(perch, "analisis", analisis)
    monkeypatch.setattr(perch, "teratas", lambda *args: [{"label": "Spesies tebakan"}])
    return calls


def test_normal_and_skip(drive, capsys):
    _, path, out = drive
    assert run(drive) == 0
    info = sf.info(wav(out))
    assert (info.samplerate, info.channels, info.subtype) == (48000, 1, "PCM_16")
    assert (wav(out).parent / "CONFIG.TXT").read_bytes() == (path.parent / "CONFIG.TXT").read_bytes()
    row = rows(out)[0]
    assert (row["par"], row["tanggal"], row["waktu"]) == ("PAR001", "2026-11-18", "2026-11-18 17:30:00")
    before = wav(out).stat().st_mtime_ns
    assert run(drive) == 0
    assert wav(out).stat().st_mtime_ns == before
    assert len(rows(out)) == 1
    assert "semua hasil sudah lengkap" in capsys.readouterr().err


def test_interrupt_midfile_resume(drive, monkeypatch, mock_perch, capsys):
    _, _, out = drive
    original = perch.analisis

    def interrupt(*args):
        raise KeyboardInterrupt

    monkeypatch.setattr(perch, "analisis", interrupt)
    assert run(drive, "--perch") == 130
    assert wav(out).exists()
    assert not embedding(out).exists()
    message = capsys.readouterr().err
    assert "Progres tersimpan" in message and "Traceback" not in message
    before = wav(out).stat().st_mtime_ns
    monkeypatch.setattr(perch, "analisis", original)
    assert run(drive, "--perch") == 0
    assert wav(out).stat().st_mtime_ns == before
    assert len(rows(out)) == 1 and rows(out)[0]["status"] == "ok"
    assert embedding(out).exists()
    assert len(mock_perch) == 1


def test_interrupt_wav_write_is_atomic(drive, monkeypatch):
    _, _, out = drive
    original = batch.simpan_wav

    def interrupt(path, *args):
        path.write_bytes(b"partial")
        raise KeyboardInterrupt

    monkeypatch.setattr(batch, "simpan_wav", interrupt)
    assert run(drive) == 130
    assert not wav(out).exists()
    assert not list(out.rglob(".batch-*"))
    monkeypatch.setattr(batch, "simpan_wav", original)
    assert run(drive) == 0
    assert len(rows(out)) == 1


def test_trial_then_perch_and_missing_embedding(drive, mock_perch, monkeypatch):
    _, _, out = drive
    assert run(drive, "--batas", "20") == 0
    before = wav(out).stat().st_mtime_ns

    def no_pipeline(*args):
        pytest.fail("Ringkasan sukses tidak perlu disaring ulang")

    monkeypatch.setattr(batch.pipeline, "jalankan", no_pipeline)
    assert run(drive, "--perch") == 0
    assert wav(out).stat().st_mtime_ns == before
    assert len(rows(out)) == 1
    assert rows(out)[0]["tebakan_perch_belum_terverifikasi"] == "Spesies tebakan"
    assert "perch_amfibi_teratas" not in rows(out)[0]
    expected, _ = sf.read(wav(out), dtype="float32")
    np.testing.assert_array_equal(mock_perch[0][0], expected)
    assert run(drive, "--perch") == 0
    assert len(mock_perch) == 1
    embedding(out).unlink()
    assert run(drive, "--perch") == 0
    assert len(mock_perch) == 2 and embedding(out).exists()


def test_missing_input(tmp_path, capsys):
    out = tmp_path / "out"
    assert batch.main(["--masukan", str(tmp_path / "missing"), "--keluaran", str(out)]) == 2
    assert "folder masukan tidak ditemukan" in capsys.readouterr().err
    assert not out.exists()


def test_empty_window(drive, capsys):
    _, path, _ = drive
    path.rename(path.with_name("20261118_120000.wav"))
    assert run(drive) == 0
    text = capsys.readouterr().err
    assert "Tidak ada file WAV/FLAC" in text and "Selesai" not in text


@pytest.mark.parametrize("content", [b"", b"not a WAV"])
def test_failure_retry_one_row(drive, capsys, content):
    _, path, out = drive
    good = path.read_bytes()
    path.write_bytes(content)
    assert run(drive) == 1
    assert run(drive) == 1
    assert len(rows(out)) == 1
    assert "tidak dapat dibaca" in rows(out)[0]["status"]
    text = capsys.readouterr().err
    assert "ffmpeg" not in text and "Traceback" not in text
    path.write_bytes(good)
    assert run(drive) == 0
    assert len(rows(out)) == 1 and rows(out)[0]["status"] == "ok"


def test_csv_interrupt_preserves_previous_rows(drive, monkeypatch):
    _, _, out = drive
    assert run(drive) == 0
    before = (out / "ringkasan.csv").read_bytes()

    def interrupt(*args, **kwargs):
        raise KeyboardInterrupt

    monkeypatch.setattr(csv.DictWriter, "writerows", interrupt)
    assert run(drive) == 130
    assert (out / "ringkasan.csv").read_bytes() == before
    assert not list(out.rglob(".batch-*"))


def test_legacy_csv_migrated_and_deduplicated(drive):
    _, _, out = drive
    assert run(drive) == 0
    row = rows(out)[0]
    row["perch_amfibi_teratas"] = "Tebakan lama"
    del row["tebakan_perch_belum_terverifikasi"]
    with (out / "ringkasan.csv").open("w", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=list(row))
        writer.writeheader()
        writer.writerows([row, row])
    assert run(drive) == 0
    assert len(rows(out)) == 1
    assert rows(out)[0]["tebakan_perch_belum_terverifikasi"] == "Tebakan lama"
