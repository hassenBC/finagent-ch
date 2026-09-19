"""Download the PDFs listed in data/sources.csv into data/raw/ and record their sha256."""

from __future__ import annotations

import csv
import hashlib
import urllib.request
from pathlib import Path

from finagent.config import ROOT

SOURCES = ROOT / "data" / "sources.csv"
RAW = ROOT / "data" / "raw"


def raw_path(row: dict[str, str]) -> Path:
    return RAW / f"{row['bank']}_{row['year']}_{row['doc_type']}.pdf"


def read_sources(path: Path = SOURCES) -> list[dict[str, str]]:
    with open(path, newline="") as f:
        return list(csv.DictReader(f))


def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for block in iter(lambda: f.read(1 << 20), b""):
            h.update(block)
    return h.hexdigest()


def fetch(url: str, dest: Path) -> None:
    req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
    with urllib.request.urlopen(req, timeout=120) as r, open(dest, "wb") as f:
        while chunk := r.read(1 << 20):
            f.write(chunk)
    with open(dest, "rb") as f:
        if f.read(5) != b"%PDF-":
            dest.unlink()
            raise ValueError(f"not a PDF: {url}")


def download_all() -> None:
    RAW.mkdir(parents=True, exist_ok=True)
    rows = read_sources()
    for row in rows:
        dest = raw_path(row)
        if not dest.exists():
            print(f"downloading {dest.name}")
            fetch(row["url"], dest)
        digest = sha256_file(dest)
        if row["sha256"] and row["sha256"] != digest:
            raise RuntimeError(f"{dest.name}: sha256 changed ({row['sha256'][:8]} -> {digest[:8]})")
        row["sha256"] = digest
    with open(SOURCES, "w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=list(rows[0]), lineterminator="\n")
        w.writeheader()
        w.writerows(rows)


if __name__ == "__main__":
    download_all()
