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
CUSTOM_MARK = ".cohort_studio_custom"   # marks a folder built from the user's own tables (custom.py)
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

# ---------------------------------------------------------------- where the files are
# A data folder holds sample_manifest.csv, slide_manifest.csv and raw/. A *release* folder (built by the
# challenge's make_release.py, e.g. data/tcga-brca/releases/practice-B) holds only changed raw files at its top
# level, plus CHANGES.json. With a release, each file the release has is read from it; everything else (the
# manifests, unchanged layers) comes from the data folder. Choose one with ONCOSYS_RELEASE (a folder, or a
# name under <data>/releases/), with `run_cohort.py --release`, in the app's sidebar, or by pointing
# ONCOSYS_DATA (or `ddir`) at the release folder itself.

def _challenge_default() -> Path:
    return Path(__file__).resolve().parents[2] / "oncosys-hackathon-challenge" / "data" / "tcga-brca"


def _configured_base() -> Path:
    env = os.environ.get("ONCOSYS_DATA")
    return Path(env).expanduser().resolve() if env else _challenge_default()


def _is_release(d: Path) -> bool:
    return not (d / BASE_FILE).exists() and any((d / Path(t["file"]).name).exists() for t in TABLES.values())


def _split(d: Path) -> tuple[Path, Path | None]:
    """(data folder, release folder or None) for a location."""
    if not _is_release(d):
        return d, None
    for parent in d.parents:
        if (parent / BASE_FILE).exists():
            return parent, d
    base = _configured_base()
    return (base if (base / BASE_FILE).exists() else _challenge_default()), d


def location(ddir: str | Path | None = None) -> Path:
    """The folder data is read from: a data folder, or a release folder of changed raw files."""
    if ddir:
        return Path(ddir).expanduser().resolve()
    base = _configured_base()
    rel = os.environ.get("ONCOSYS_RELEASE", "").strip()
    if rel:
        r = Path(rel).expanduser()
        if not r.exists():
            r = _split(base)[0] / "releases" / rel
        return r.resolve()
    return base


def data_dir(ddir: str | Path | None = None) -> Path:
    return _split(location(ddir))[0]


def release_dir(ddir: str | Path | None = None) -> Path | None:
    return _split(location(ddir))[1]


def available_releases(ddir: str | Path | None = None) -> list[str]:
    folder = data_dir(ddir) / "releases"
    return sorted(p.name for p in folder.iterdir() if p.is_dir() and _is_release(p)) if folder.exists() else []


def file_path(rel: str, ddir: str | Path | None = None) -> Path:
    """Where to read `rel` (e.g. "raw/clinical.tsv"): the release's copy if it has one, else the data folder's."""
    base, release = _split(location(ddir))
    if release is not None and (release / Path(rel).name).exists():
        return release / Path(rel).name
    return base / rel


def _sha256(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


@functools.lru_cache(maxsize=None)
def check_data(ddir: str | None = None) -> dict[str, str]:
    """Status of every file Cohort Studio reads: 'ok', 'missing', 'CHANGED' (differs from the frozen
    checksum) or 'release' (read from the chosen release folder, which is meant to differ)."""
    d = data_dir(ddir)
    release = release_dir(ddir)
    status = {}
    frozen = {}
    src = d / "sources.csv"
    if src.exists():
        frozen = {r["file"]: r["sha256"] for r in csv.DictReader(open(src, encoding="utf-8"))}
    for rel in [BASE_FILE] + [t["file"] for t in TABLES.values()]:
        p = file_path(rel, ddir)
        name = Path(rel).name
        if not p.exists():
            status[rel] = "missing"
        elif release is not None and p.parent == release:
            status[rel] = "release"
        elif name in frozen and _sha256(p) != frozen[name]:
            status[rel] = "CHANGED"
        else:
            status[rel] = "ok"
    return status


def file_fingerprints(ddir: str | None = None) -> dict[str, str]:
    out = {}
    for rel in [BASE_FILE] + [t["file"] for t in TABLES.values()]:
        p = file_path(rel, ddir)
        if p.exists():
            out[rel] = _sha256(p)
    return out


def is_custom(ddir: str | Path | None = None) -> bool:
    return (data_dir(ddir) / CUSTOM_MARK).exists()


@functools.lru_cache(maxsize=None)
def _load(name: str, ddir: str | None) -> pd.DataFrame:
    if is_custom(ddir):                       # the user's own tables: plain CSVs, keys already named
        if name != "samples" and name not in TABLES:
            raise KeyError(name)
        return pd.read_csv(file_path(BASE_FILE if name == "samples" else TABLES[name]["file"], ddir))
    if name == "samples":
        return pd.read_csv(file_path(BASE_FILE, ddir))
    if name not in TABLES:
        raise KeyError(name)
    path = file_path(TABLES[name]["file"], ddir)
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
    """Return a copy so callers can't mutate the cache. The cache key is the resolved location, so
    switching release (ONCOSYS_RELEASE) never serves the old files."""
    return _load(name, str(location(ddir))).copy()
