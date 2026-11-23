"""Kelompok dengar dari kemiripan embedding Perch, tanpa tebakan jenis."""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass

import numpy as np
from sklearn.cluster import MiniBatchKMeans
from sklearn.preprocessing import normalize


@dataclass
class Kelompok:
    id: str
    anggota: list[dict]
    contoh: list[dict]

    def ringkasan(self) -> dict:
        return {
            "id": self.id,
            "jumlah": len(self.anggota),
            "belum_dilabel": sum(j["label"] is None for j in self.anggota),
            "contoh": self.contoh,
        }


def buat(rows: list[dict]) -> list[Kelompok]:
    if not rows:
        return []
    x = normalize(np.stack([np.frombuffer(j["embedding"], np.float32) for j in rows]))
    jumlah = min(12, max(1, round(len(rows) ** 0.5)))
    model = MiniBatchKMeans(n_clusters=jumlah, random_state=0, n_init=3).fit(x)
    kelompok = []
    for i, pusat in enumerate(model.cluster_centers_):
        indeks = np.flatnonzero(model.labels_ == i)
        if not len(indeks):
            continue
        anggota = [{k: v for k, v in rows[j].items() if k != "embedding"} for j in indeks]
        kunci = [(j["rekaman_id"], j["idx"]) for j in anggota]
        kid = hashlib.sha256(json.dumps(kunci).encode()).hexdigest()
        jarak = np.linalg.norm(x[indeks] - pusat, axis=1)
        urut = np.argsort(jarak, kind="stable").tolist()
        # Dengarkan pusat dan tepi kelompok untuk menilai variasinya.
        contoh = [anggota[j] for j in dict.fromkeys([urut[0], urut[-1], urut[len(urut) // 2]])]
        kelompok.append(Kelompok(kid, anggota, contoh))
    return sorted(kelompok, key=lambda k: (-len(k.anggota), k.id))
