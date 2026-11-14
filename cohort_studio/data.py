"""Load the frozen TCGA-BRCA tables Cohort Studio works with.

Data lives in the challenge repo (not copied here). Set ONCOSYS_DATA to its
data/tcga-brca folder, or clone the challenge repo next to this one.
"""
from __future__ import annotations

import csv
import functools
import gzip
import hashlib
import os
from pathlib import Path

import pandas as pd

KEYS = ("sample_id", "patient_id")
BASE_FILE = "sample_manifest.csv"

# Tables a cohort can be joined to. "grain" = what one row is.
TABLES = {
    "samples": {
        "file": BASE_FILE,
        "grain": "sample",
        "about": "Official sample manifest, one row per sample. Use for patient-level existence checks.",
    },
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
    "mutation": {
        "file": "raw/mutation_gene_level.tsv.gz",
        "grain": "sample-gene",
        "about": "Gene-level mutation presence, one row per mutated sample-gene pair.",
    },
    "slides": {
        "file": "slide_manifest.csv",
        "grain": "slide",
        "about": "Pathology slides, several per sample. slide_kind is 'diagnostic (FFPE)' or 'frozen, ...'.",
    },
}

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
        frozen = {r["file"]: r["sha256"] for r in csv.DictReader(open(src, encoding="utf-8"))}
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
    elif name == "mutation":
        manifest = _load("samples", ddir)
        patients = dict(zip(manifest["sample_id"].astype(str), manifest["patient_id"].astype(str)))
        records = []
        seen_genes = set()
        with gzip.open(path, "rt", encoding="utf-8", newline="") as f:
            reader = csv.reader(f, delimiter="\t")
            header = next(reader, None)
            if not header or header[0] != "sample":
                raise ValueError(f"{path} must have a first column named 'sample' (the gene symbol).")
            sample_ids = header[1:]
            if not sample_ids or len(sample_ids) != len(set(sample_ids)):
                raise ValueError(f"{path} must contain unique sample barcode columns.")
            for line_number, row in enumerate(reader, start=2):
                if len(row) != len(header):
                    raise ValueError(f"{path} line {line_number} has {len(row)} cells; expected {len(header)}.")
                gene = row[0].strip()
                if not gene or gene in seen_genes:
                    raise ValueError(f"{path} line {line_number} has a blank or duplicate gene symbol: {gene!r}.")
                seen_genes.add(gene)
                for sample_id, value in zip(sample_ids, row[1:]):
                    if value == "1":
                        patient_id = patients.get(sample_id)
                        if patient_id is not None:
                            records.append((sample_id, patient_id, gene, True))
                    elif value != "0":
                        raise ValueError(
                            f"{path} line {line_number} has unexpected mutation value {value!r} for {gene}."
                        )
        return pd.DataFrame(records, columns=["sample_id", "patient_id", "gene", "mutated"])
    else:
        df = pd.read_csv(path)
    return df


def load(name: str, ddir: str | None = None) -> pd.DataFrame:
    """Return a copy so callers can't mutate the cache."""
    return _load(name, ddir).copy()
