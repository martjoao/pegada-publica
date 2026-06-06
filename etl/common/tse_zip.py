"""Utilities for reading and inventorying TSE bulk ZIP archives.

TSE ZIP files contain one or more semicolon-delimited CSVs encoded in
ISO-8859-1 (latin-1).  ``build_manifest`` reads each CSV header and counts
rows, returning a structured dict suitable for writing as a manifest JSON.
"""
from __future__ import annotations

import csv
import io
import zipfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List

SOURCE = "tse-dados-abertos"
ENCODING = "latin-1"
# Raw PT values as they appear in the TSE DS_CARGO column.
# VERIFY these against an actual file header before first run.
FEDERAL_CARGOS = frozenset({"DEPUTADO FEDERAL", "SENADOR", "PRESIDENTE"})


def _utcnow_iso() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def build_manifest(zip_path: Path, source_url: str) -> Dict[str, Any]:
    """Read a TSE ZIP and return a manifest dict.

    Records column names, total row count, and federal-candidate row count for
    every CSV inside the ZIP.  Raises ``ValueError`` if the ZIP has no CSVs or
    if any CSV is missing the expected ``DS_CARGO`` column.
    """
    files: List[Dict[str, Any]] = []

    with zipfile.ZipFile(zip_path) as zf:
        csv_names = [n for n in zf.namelist() if n.lower().endswith(".csv")]
        if not csv_names:
            raise ValueError(
                f"No CSV files found in {zip_path}. Found: {zf.namelist()}"
            )

        for name in csv_names:
            with zf.open(name) as raw:
                text = io.TextIOWrapper(raw, encoding=ENCODING)
                reader = csv.reader(text, delimiter=";")
                columns = next(reader)
                # Strip leading/trailing whitespace from all columns.
                # Also strip BOM sequences that appear as the first bytes of the file.
                # UTF-8 BOM (\xef\xbb\xbf) decoded as latin-1 gives the 3-char prefix 'ï»¿'.
                # Some TSE files also carry the Unicode BOM ﻿ directly.
                columns = [c.strip() for c in columns]
                if columns:
                    first = columns[0]
                    # Remove UTF-8 BOM decoded as latin-1 ('ï»¿')
                    if first.startswith("ï»¿"):
                        first = first[3:]
                    # Remove Unicode BOM character (﻿ / U+FEFF)
                    elif first.startswith("﻿"):
                        first = first[1:]
                    columns[0] = first

                if "DS_CARGO" not in columns:
                    raise ValueError(
                        f"Column 'DS_CARGO' not found in {name}. "
                        f"Available columns: {columns}"
                    )
                cargo_idx = columns.index("DS_CARGO")

                total = 0
                federal = 0
                for row in reader:
                    total += 1
                    if (
                        cargo_idx < len(row)
                        and row[cargo_idx].strip().upper() in FEDERAL_CARGOS
                    ):
                        federal += 1

                text.detach()  # detach before ZipExtFile context manager closes raw

            files.append(
                {
                    "filename": name,
                    "columns": columns,
                    "total_rows": total,
                    "federal_rows": federal,
                }
            )

    return {
        "_meta": {
            "source": SOURCE,
            "source_url": source_url,
            "fetched_at": _utcnow_iso(),
            "encoding": ENCODING,
        },
        "files": files,
    }
