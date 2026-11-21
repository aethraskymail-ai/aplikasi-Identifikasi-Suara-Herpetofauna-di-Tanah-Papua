"""Google Perch v2: embedding 1536-d per jendela 5 detik @ 32 kHz + skor kelas langsung.

Model diunduh otomatis dari Kaggle (`google/bird-vocalization-classifier/tensorFlow2/perch_v2_cpu`)
saat pertama dipakai (~390 MB), lalu tersimpan di cache kagglehub.
"""

from __future__ import annotations

import csv
import json
import os
import threading
from dataclasses import dataclass
from pathlib import Path

import numpy as np

from .audio import resample

SR_PERCH = 32000
JENDELA_S = 5
HANDLE = os.environ.get("PERCH_HANDLE", "google/bird-vocalization-classifier/tensorFlow2/perch_v2_cpu")
_DATA = Path(__file__).parent / "data"

_lock = threading.Lock()
_model = None


@dataclass
class Jendela:
    mulai_s: float
    akhir_s: float
    embedding: np.ndarray
    logit: np.ndarray


def _muat():
    global _model
    with _lock:
        if _model is None:
            import kagglehub
            import tensorflow as tf

            path = os.environ.get("PERCH_PATH") or kagglehub.model_download(HANDLE)
            m = tf.saved_model.load(path)
            labels = [r[0] for r in csv.reader(open(Path(path) / "assets" / "labels.csv"))][1:]
            _model = (m.signatures["serving_default"], labels)
    return _model


def tersedia() -> bool:
    try:
        import kagglehub  # noqa: F401
        import tensorflow  # noqa: F401
    except ImportError:
        return False
    return True


def label_amfibi() -> list[tuple[int, str]]:
    """Indeks label Perch v2 yang termasuk kelas Amphibia (dicocokkan ke genus GBIF)."""
    return [tuple(x) for x in json.load(open(_DATA / "perch_v2_amfibi.json"))]


def potong_jendela(x: np.ndarray, sr: int) -> tuple[np.ndarray, list[tuple[float, float]]]:
    y = resample(x, sr, SR_PERCH)
    n = SR_PERCH * JENDELA_S
    jumlah = max(1, int(np.ceil(len(y) / n)))
    y = np.pad(y, (0, jumlah * n - len(y)))
    batch = y.reshape(jumlah, n)
    durasi = len(x) / sr
    waktu = [(i * JENDELA_S, min((i + 1) * JENDELA_S, durasi)) for i in range(jumlah)]
    # Jendela sisa < 1 detik dibuang kecuali itu satu-satunya.
    simpan = [i for i, (a, b) in enumerate(waktu) if b - a >= 1.0 or i == 0]
    return batch[simpan], [waktu[i] for i in simpan]


def analisis(x: np.ndarray, sr: int, ukuran_batch: int = 16) -> list[Jendela]:
    import tensorflow as tf

    f, _ = _muat()
    batch, waktu = potong_jendela(x, sr)
    hasil: list[Jendela] = []
    for i in range(0, len(batch), ukuran_batch):
        out = f(inputs=tf.constant(batch[i : i + ukuran_batch], tf.float32))
        emb, logit = out["embedding"].numpy(), out["label"].numpy()
        for j in range(len(emb)):
            a, b = waktu[i + j]
            hasil.append(Jendela(round(a, 2), round(b, 2), emb[j], logit[j]))
    return hasil


def softmax(z: np.ndarray) -> np.ndarray:
    e = np.exp(z - z.max())
    return e / e.sum()


def teratas(logit: np.ndarray, k: int = 5, hanya_amfibi: bool = True) -> list[dict]:
    """Skor = softmax di antara kandidat (amfibi saja, atau semua 14.795 kelas)."""
    _, labels = _muat()
    idx = np.array([i for i, _ in label_amfibi()]) if hanya_amfibi else np.arange(len(logit))
    p = softmax(logit[idx])
    urut = np.argsort(p)[::-1][:k]
    return [{"label": labels[idx[i]], "skor": round(float(p[i]), 3)} for i in urut]
