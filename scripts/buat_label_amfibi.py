"""Membuat suarakatak/data/perch_v2_amfibi.json: label Perch v2 yang genusnya termasuk Amphibia di GBIF."""

import csv
import json
import sys
import urllib.request
from pathlib import Path

import kagglehub

BACKBONE = "d7dddbf4-2cf0-4f39-9b2a-bb099caae36c"
AMPHIBIA = 131

genus = set()
offset = 0
while True:
    url = (
        "https://api.gbif.org/v1/species/search?rank=GENUS"
        f"&highertaxon_key={AMPHIBIA}&datasetKey={BACKBONE}&limit=1000&offset={offset}"
    )
    data = json.load(urllib.request.urlopen(url, timeout=60))
    genus.update((r.get("canonicalName") or r["genus"]).split()[0] for r in data["results"])
    offset += 1000
    if data["endOfRecords"]:
        break

path = Path(kagglehub.model_download("google/bird-vocalization-classifier/tensorFlow2/perch_v2_cpu"))
labels = [r[0] for r in csv.reader(open(path / "assets" / "labels.csv"))][1:]
amfibi = [(i, nama) for i, nama in enumerate(labels) if " " in nama and nama.split()[0] in genus]
out = Path(__file__).resolve().parents[1] / "suarakatak" / "data" / "perch_v2_amfibi.json"
json.dump(amfibi, open(out, "w"))
print(f"{len(amfibi)} label amfibi -> {out}", file=sys.stderr)
