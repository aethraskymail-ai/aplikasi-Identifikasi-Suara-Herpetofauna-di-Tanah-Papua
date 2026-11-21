"""Klasifier kecil (regresi logistik) di atas embedding Perch dari label pemilik data."""

from __future__ import annotations

import json
import sqlite3
import threading
import time
from pathlib import Path

import numpy as np

_lock = threading.Lock()


class Penyimpanan:
    def __init__(self, path: Path):
        self.path = path
        path.parent.mkdir(parents=True, exist_ok=True)
        with self._db() as db:
            db.executescript(
                """
                CREATE TABLE IF NOT EXISTS rekaman (
                  id TEXT PRIMARY KEY, nama_file TEXT, dibuat REAL, ringkasan TEXT
                );
                CREATE TABLE IF NOT EXISTS jendela (
                  rekaman_id TEXT, idx INTEGER, mulai_s REAL, akhir_s REAL, embedding BLOB,
                  label TEXT, dilabel REAL, PRIMARY KEY (rekaman_id, idx)
                );
                """
            )
        self._model = None
        self._model_versi = None

    def _db(self):
        db = sqlite3.connect(self.path)
        db.row_factory = sqlite3.Row
        return db

    def simpan_rekaman(self, rid: str, nama_file: str, ringkasan: dict, jendela: list) -> None:
        with _lock, self._db() as db:
            db.execute(
                "INSERT OR REPLACE INTO rekaman VALUES (?,?,?,?)",
                (rid, nama_file, time.time(), json.dumps(ringkasan)),
            )
            db.executemany(
                "INSERT OR REPLACE INTO jendela (rekaman_id, idx, mulai_s, akhir_s, embedding) VALUES (?,?,?,?,?)",
                [(rid, i, j.mulai_s, j.akhir_s, j.embedding.astype(np.float32).tobytes()) for i, j in enumerate(jendela)],
            )

    def daftar_rekaman(self) -> list[dict]:
        with self._db() as db:
            rows = db.execute(
                """SELECT r.id, r.nama_file, r.dibuat,
                          COUNT(j.idx) AS jendela, COUNT(j.label) AS dilabel
                   FROM rekaman r LEFT JOIN jendela j ON j.rekaman_id = r.id
                   GROUP BY r.id ORDER BY r.dibuat DESC"""
            ).fetchall()
        return [dict(r) for r in rows]

    def ambil_rekaman(self, rid: str) -> dict | None:
        with self._db() as db:
            r = db.execute("SELECT * FROM rekaman WHERE id=?", (rid,)).fetchone()
            if not r:
                return None
            labels = {
                row["idx"]: row["label"]
                for row in db.execute("SELECT idx, label FROM jendela WHERE rekaman_id=?", (rid,))
            }
        data = json.loads(r["ringkasan"])
        for j in data.get("jendela", []):
            j["label"] = labels.get(j["idx"])
        return data

    def hapus_rekaman(self, rid: str) -> None:
        with _lock, self._db() as db:
            db.execute("DELETE FROM jendela WHERE rekaman_id=?", (rid,))
            db.execute("DELETE FROM rekaman WHERE id=?", (rid,))

    def beri_label(self, rid: str, idx: int, label: str | None) -> None:
        label = (label or "").strip() or None
        with _lock, self._db() as db:
            db.execute(
                "UPDATE jendela SET label=?, dilabel=? WHERE rekaman_id=? AND idx=?",
                (label, time.time() if label else None, rid, idx),
            )

    def data_latih(self) -> tuple[np.ndarray, list[str], list[dict]]:
        with self._db() as db:
            rows = db.execute(
                """SELECT j.rekaman_id, j.idx, j.mulai_s, j.akhir_s, j.embedding, j.label, r.nama_file
                   FROM jendela j JOIN rekaman r ON r.id = j.rekaman_id
                   WHERE j.label IS NOT NULL ORDER BY j.dilabel"""
            ).fetchall()
        if not rows:
            return np.zeros((0, 1536), np.float32), [], []
        x = np.stack([np.frombuffer(r["embedding"], np.float32) for r in rows])
        meta = [
            {k: r[k] for k in ("rekaman_id", "idx", "mulai_s", "akhir_s", "label", "nama_file")} for r in rows
        ]
        return x, [r["label"] for r in rows], meta

    def statistik_label(self) -> dict[str, int]:
        with self._db() as db:
            rows = db.execute(
                "SELECT label, COUNT(*) n FROM jendela WHERE label IS NOT NULL GROUP BY label ORDER BY n DESC"
            ).fetchall()
        return {r["label"]: r["n"] for r in rows}

    def latih(self) -> dict:
        from sklearn.linear_model import LogisticRegression
        from sklearn.model_selection import StratifiedKFold, cross_val_score
        from sklearn.pipeline import make_pipeline
        from sklearn.preprocessing import StandardScaler

        x, y, _ = self.data_latih()
        kelas, jumlah = np.unique(y, return_counts=True) if y else (np.array([]), np.array([]))
        if len(kelas) < 2:
            self._model = None
            return {"siap": False, "pesan": "Butuh label minimal 2 kelas (mis. satu jenis katak + 'bukan katak').",
                    "kelas": dict(zip(kelas.tolist(), jumlah.tolist()))}
        model = make_pipeline(StandardScaler(), LogisticRegression(max_iter=2000, class_weight="balanced", C=0.5))
        info: dict = {"siap": True, "kelas": dict(zip(kelas.tolist(), jumlah.tolist())), "n": len(y)}
        lipatan = int(min(5, jumlah.min()))
        if lipatan >= 2:
            skor = cross_val_score(model, x, y, cv=StratifiedKFold(lipatan, shuffle=True, random_state=0))
            info["akurasi_cv"] = round(float(skor.mean()), 3)
            info["lipatan_cv"] = lipatan
        else:
            info["akurasi_cv"] = None
            info["pesan"] = "Akurasi validasi silang muncul setelah tiap kelas punya ≥2 label."
        model.fit(x, y)
        self._model = model
        return info

    def model(self):
        if self._model is None:
            x, y, _ = self.data_latih()
            if len(set(y)) >= 2:
                self.latih()
        return self._model

    def prediksi(self, embedding: np.ndarray, k: int = 3) -> list[list[dict]]:
        model = self.model()
        if model is None:
            return [[] for _ in range(len(embedding))]
        p = model.predict_proba(embedding)
        kelas = model.classes_
        return [
            [{"label": str(kelas[i]), "skor": round(float(row[i]), 3)} for i in np.argsort(row)[::-1][:k]]
            for row in p
        ]

    def embedding_rekaman(self, rid: str) -> np.ndarray:
        with self._db() as db:
            rows = db.execute(
                "SELECT embedding FROM jendela WHERE rekaman_id=? ORDER BY idx", (rid,)
            ).fetchall()
        return np.stack([np.frombuffer(r["embedding"], np.float32) for r in rows]) if rows else np.zeros((0, 1536))
