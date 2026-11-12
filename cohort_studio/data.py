"""Load the frozen TCGA-BRCA tables Cohort Studio works with.

Data lives in the challenge repo (not copied here). Set ONCOSYS_DATA to its
data/tcga-brca folder, or clone the challenge repo next to this one.
"""
from __future__ import annotations

import csv
import functools
import hashlib
import os
from pathlib import Path

import pandas as pd

KEYS = ("sample_id", "patient_id")

# Tables a cohort can be joined to. "grain" = what one row is.
TABLES = {
    "clinical": {
        "file": "raw/clinical.tsv",
        "grain": "sample",
        "about": "Clinical record, one row per sample (normal-tissue samples have rows too). 194 columns.",
    },
    "survival": {
        "file": "raw/survival.tsv",
        "grain": "sample",
        "about": "Curated survival (OS, DSS, DFI, PFI and their .time columns), one row per sample.",
    },
    "slides": {
        "file": "slide_manifest.csv",
        "grain": "slide",
        "about": "Pathology slides, several per sample. slide_kind is 'diagnostic (FFPE)' or 'frozen, ...'.",
    },
}

BASE_FILE = "sample_manifest.csv"


def data_dir() -> Path:
    env = os.environ.get("ONCOSYS_DATA")
    if env:
        return Path(env).expanduser().resolve()
    return Path(__file__).resolve().parents[2] / "oncosys-hackathon-challenge" / "data" / "tcga-brca"


def _sha256(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


@functools.lru_cache(maxsize=None)
def check_data(ddir: str | None = None) -> dict[str, str]:
    """Status of every file Cohort Studio reads: 'ok', 'missing' or 'CHANGED'."""
    d = Path(ddir) if ddir else data_dir()
    status = {}
    frozen = {}
    src = d / "sources.csv"
    if src.exists():
        frozen = {r["file"]: r["sha256"] for r in csv.DictReader(open(src))}
    for rel in [BASE_FILE] + [t["file"] for t in TABLES.values()]:
        p = d / rel
        name = Path(rel).name
        if not p.exists():
            status[rel] = "missing"
        elif name in frozen and _sha256(p) != frozen[name]:
            status[rel] = "CHANGED"
        else:
            status[rel] = "ok"
    return status


def file_fingerprints(ddir: str | None = None) -> dict[str, str]:
    d = Path(ddir) if ddir else data_dir()
    out = {}
    for rel in [BASE_FILE] + [t["file"] for t in TABLES.values()]:
        p = d / rel
        if p.exists():
            out[rel] = _sha256(p)
    return out


@functools.lru_cache(maxsize=None)
def _load(name: str, ddir: str | None) -> pd.DataFrame:
    d = Path(ddir) if ddir else data_dir()
    if name == "samples":
        return pd.read_csv(d / BASE_FILE)
    if name not in TABLES:
        raise KeyError(name)
    path = d / TABLES[name]["file"]
    if not path.exists():
        raise FileNotFoundError(
            f"{path} not found. Run `python data/tcga-brca/fetch.py` in the challenge repo, "
            "or set ONCOSYS_DATA to its data/tcga-brca folder."
        )
    if name == "clinical":
        # clinical.tsv's own `patient_id` is only the 4-character barcode suffix (e.g. "AAAU"),
        # so keep it as patient_suffix and use the full 12-character barcode as the key.
        df = pd.read_csv(path, sep="\t", low_memory=False).rename(
            columns={"sampleID": "sample_id", "patient_id": "patient_suffix"})
        df.insert(1, "patient_id", df["sample_id"].str[:12])
    elif name == "survival":
        df = pd.read_csv(path, sep="\t").rename(columns={"sample": "sample_id", "_PATIENT": "patient_id"})
    else:
        df = pd.read_csv(path)
    return df


def load(name: str, ddir: str | None = None) -> pd.DataFrame:
    """Return a copy so callers can't mutate the cache."""
    return _load(name, ddir).copy()
