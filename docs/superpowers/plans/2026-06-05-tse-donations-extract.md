# TSE Donations Extract Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Download TSE bulk campaign donation CSVs and candidate registries for federal elections 2018 and 2022, saving them as raw artifacts with column-inventorying manifests.

**Architecture:** Pure extract — files saved verbatim under `data/raw/tse/`. A new `TseDownloader` class handles large streaming binary downloads. A shared `common/tse_zip.py` utility reads ZIP contents to build manifests. Two thin extract scripts (`extract/tse/receitas.py`, `extract/tse/candidatos.py`) wire everything together using the same injectable-dependency `run()` pattern as existing scripts.

**Tech Stack:** Python 3.8, `requests`, stdlib `zipfile` + `csv` + `io`, `pytest`. No new dependencies.

**Spec:** `docs/superpowers/specs/2026-06-05-tse-donations-extract-design.md`

---

## File Map

| File | Action | Responsibility |
|---|---|---|
| `etl/common/http_client.py` | Modify | Add `TseDownloader` — streaming binary download with retry |
| `etl/common/tse_zip.py` | Create | `build_manifest()` — reads TSE ZIP, extracts column names and row counts |
| `etl/common/paths.py` | Modify | Add 4 TSE path helpers |
| `etl/extract/tse/receitas.py` | Create | Download receitas_candidatos ZIPs + write manifests |
| `etl/extract/tse/candidatos.py` | Create | Download consulta_cand ZIPs + write manifests |
| `etl/tests/test_tse_downloader.py` | Create | TseDownloader unit tests |
| `etl/tests/test_tse_zip.py` | Create | build_manifest unit tests |
| `etl/tests/test_tse_receitas_extract.py` | Create | receitas run() integration tests |
| `etl/tests/test_tse_candidatos_extract.py` | Create | candidatos run() integration tests |
| `etl/tests/test_paths.py` | Modify | Add TSE path tests |

---

### Task 1: TSE path helpers

**Files:**
- Modify: `etl/common/paths.py`
- Modify: `etl/tests/test_paths.py`

- [ ] **Step 1: Write the failing tests**

Append to `etl/tests/test_paths.py`:

```python
def test_tse_receitas_zip_path_uses_year_filename():
    p = paths.tse_receitas_zip_path(2022, base=Path("/tmp/raw"))
    assert p == Path("/tmp/raw/tse/receitas/2022.zip")


def test_tse_receitas_zip_path_defaults_under_data_raw():
    p = paths.tse_receitas_zip_path(2018)
    assert p.parts[-4:] == ("raw", "tse", "receitas", "2018.zip")


def test_tse_receitas_manifest_path_uses_year_filename():
    p = paths.tse_receitas_manifest_path(2022, base=Path("/tmp/raw"))
    assert p == Path("/tmp/raw/tse/receitas/2022_manifest.json")


def test_tse_candidatos_zip_path_uses_year_filename():
    p = paths.tse_candidatos_zip_path(2022, base=Path("/tmp/raw"))
    assert p == Path("/tmp/raw/tse/candidatos/2022.zip")


def test_tse_candidatos_manifest_path_uses_year_filename():
    p = paths.tse_candidatos_manifest_path(2022, base=Path("/tmp/raw"))
    assert p == Path("/tmp/raw/tse/candidatos/2022_manifest.json")
```

- [ ] **Step 2: Run to verify tests fail**

```
cd etl && .venv/bin/python -m pytest tests/test_paths.py -k "tse" -v
```

Expected: 5 FAILs with `AttributeError: module 'common.paths' has no attribute 'tse_receitas_zip_path'`

- [ ] **Step 3: Implement the path helpers**

Append to `etl/common/paths.py` (after the existing `db_path` function):

```python
def tse_receitas_zip_path(year: int, base: Optional[Path] = None) -> Path:
    """Return the raw landing file path for a given year's receitas_candidatos ZIP."""
    base = base if base is not None else DATA_RAW
    return base / "tse" / "receitas" / f"{year}.zip"


def tse_receitas_manifest_path(year: int, base: Optional[Path] = None) -> Path:
    """Return the manifest JSON path for a given year's receitas ZIP."""
    base = base if base is not None else DATA_RAW
    return base / "tse" / "receitas" / f"{year}_manifest.json"


def tse_candidatos_zip_path(year: int, base: Optional[Path] = None) -> Path:
    """Return the raw landing file path for a given year's consulta_cand ZIP."""
    base = base if base is not None else DATA_RAW
    return base / "tse" / "candidatos" / f"{year}.zip"


def tse_candidatos_manifest_path(year: int, base: Optional[Path] = None) -> Path:
    """Return the manifest JSON path for a given year's candidatos ZIP."""
    base = base if base is not None else DATA_RAW
    return base / "tse" / "candidatos" / f"{year}_manifest.json"
```

- [ ] **Step 4: Run to verify tests pass**

```
cd etl && .venv/bin/python -m pytest tests/test_paths.py -k "tse" -v
```

Expected: 5 PASSes

- [ ] **Step 5: Run full test suite (no regressions)**

```
cd etl && .venv/bin/python -m pytest -q
```

Expected: all existing tests still pass

- [ ] **Step 6: Commit**

```bash
git add etl/common/paths.py etl/tests/test_paths.py
git commit -m "feat(etl): add TSE path helpers for receitas and candidatos ZIPs"
```

---

### Task 2: TseDownloader

**Files:**
- Modify: `etl/common/http_client.py`
- Create: `etl/tests/test_tse_downloader.py`

- [ ] **Step 1: Write the failing tests**

Create `etl/tests/test_tse_downloader.py`:

```python
"""Tests for TseDownloader — the streaming binary download client."""
from pathlib import Path
from unittest.mock import MagicMock

import pytest
import requests

from common.http_client import TseDownloader


# ── helpers ─────────────────────────────────────────────────────────────────

def _make_response(status: int = 200, content: bytes = b"data", content_length: int = None):
    resp = MagicMock()
    resp.status_code = status
    resp.headers = {}
    if content_length is not None:
        resp.headers["Content-Length"] = str(content_length)
    resp.iter_content = MagicMock(return_value=iter([content]))
    if status >= 400:
        http_err = requests.HTTPError(response=resp)
        resp.raise_for_status = MagicMock(side_effect=http_err)
    else:
        resp.raise_for_status = MagicMock()
    return resp


def _make_session(*responses):
    """Session whose .get() returns responses in order."""
    session = MagicMock()
    session.get = MagicMock(side_effect=list(responses))
    return session


# ── tests ────────────────────────────────────────────────────────────────────

def test_download_writes_file(tmp_path):
    session = _make_session(_make_response(content=b"zip bytes"))
    dl = TseDownloader(session=session)
    dest = tmp_path / "out.zip"
    dl.download("http://example.com/file.zip", dest)
    assert dest.read_bytes() == b"zip bytes"


def test_download_atomic_rename(tmp_path):
    """Destination file must not exist mid-write; temp file cleaned up after."""
    session = _make_session(_make_response(content=b"data"))
    dl = TseDownloader(session=session)
    dest = tmp_path / "out.zip"
    dl.download("http://example.com/file.zip", dest)
    assert dest.exists()
    assert not (tmp_path / "out.zip.tmp").exists()


def test_download_creates_parent_dirs(tmp_path):
    session = _make_session(_make_response(content=b"data"))
    dl = TseDownloader(session=session)
    dest = tmp_path / "a" / "b" / "out.zip"
    dl.download("http://example.com/file.zip", dest)
    assert dest.read_bytes() == b"data"


def test_download_retries_on_503(tmp_path):
    err_resp = _make_response(status=503)
    ok_resp = _make_response(content=b"ok")
    session = _make_session(err_resp, ok_resp)
    dl = TseDownloader(session=session, backoff_base=0)
    dest = tmp_path / "out.zip"
    dl.download("http://example.com/file.zip", dest)
    assert dest.read_bytes() == b"ok"
    assert session.get.call_count == 2


def test_download_retries_on_connection_error(tmp_path):
    session = MagicMock()
    ok_resp = _make_response(content=b"ok")
    session.get = MagicMock(
        side_effect=[requests.ConnectionError("network down"), ok_resp]
    )
    dl = TseDownloader(session=session, backoff_base=0)
    dest = tmp_path / "out.zip"
    dl.download("http://example.com/file.zip", dest)
    assert dest.read_bytes() == b"ok"


def test_download_raises_immediately_on_404(tmp_path):
    session = _make_session(_make_response(status=404))
    dl = TseDownloader(session=session, max_retries=3, backoff_base=0)
    with pytest.raises(requests.HTTPError):
        dl.download("http://example.com/file.zip", tmp_path / "out.zip")
    assert session.get.call_count == 1  # no retry


def test_download_raises_on_content_length_mismatch(tmp_path):
    # Server says 100 bytes, sends 5
    session = _make_session(_make_response(content=b"short", content_length=100))
    dl = TseDownloader(session=session, max_retries=0)
    dest = tmp_path / "out.zip"
    with pytest.raises(ValueError, match="Content-length mismatch"):
        dl.download("http://example.com/file.zip", dest)
    assert not dest.exists()
    assert not (tmp_path / "out.zip.tmp").exists()


def test_download_exhausts_retries_and_raises(tmp_path):
    session = MagicMock()
    session.get = MagicMock(side_effect=requests.ConnectionError("always down"))
    dl = TseDownloader(session=session, max_retries=2, backoff_base=0)
    with pytest.raises(requests.ConnectionError):
        dl.download("http://example.com/file.zip", tmp_path / "out.zip")
    assert session.get.call_count == 3  # initial + 2 retries
```

- [ ] **Step 2: Run to verify tests fail**

```
cd etl && .venv/bin/python -m pytest tests/test_tse_downloader.py -v
```

Expected: ImportError or AttributeError for `TseDownloader`

- [ ] **Step 3: Implement TseDownloader**

Add to `etl/common/http_client.py` after the `SenadoClient` class (keep existing code untouched).

First check the top of `http_client.py` for these imports and add any that are missing:
```python
import os
from pathlib import Path
```

Then add the class:

```python


class TseDownloader:
    """Streaming downloader for large TSE bulk files (ZIPs, CSV archives).

    Unlike ``CamaraClient``/``SenadoClient`` which are designed for paginated
    JSON API calls, this streams binary content to a temp file and renames
    atomically.  Retry behaviour mirrors the existing clients.
    """

    def __init__(
        self,
        session: Optional[requests.Session] = None,
        max_retries: int = 3,
        backoff_base: float = 0.5,
        chunk_size: int = 65536,
        timeout: float = 120.0,
        user_agent: str = DEFAULT_USER_AGENT,
    ) -> None:
        self.max_retries = max_retries
        self.backoff_base = backoff_base
        self.chunk_size = chunk_size
        self.timeout = timeout
        self.session = session or requests.Session()
        self.session.headers.update({"User-Agent": user_agent})

    def download(self, url: str, dest_path: Path) -> None:
        """Stream ``url`` to ``dest_path`` via a temp file (atomic rename on success).

        Retries on 5xx, timeouts, and connection errors with exponential backoff.
        Raises immediately on 4xx (not retryable).
        Raises ``ValueError`` on Content-Length mismatch; removes the temp file.
        """
        dest_path = Path(dest_path)
        dest_path.parent.mkdir(parents=True, exist_ok=True)
        tmp_path = dest_path.with_name(dest_path.name + ".tmp")

        last_exc: Optional[Exception] = None
        for attempt in range(self.max_retries + 1):
            try:
                response = self.session.get(url, stream=True, timeout=self.timeout)
                if response.status_code >= 500:
                    response.raise_for_status()
                response.raise_for_status()

                content_length = response.headers.get("Content-Length")
                expected = int(content_length) if content_length else None

                written = 0
                with open(tmp_path, "wb") as fh:
                    for chunk in response.iter_content(chunk_size=self.chunk_size):
                        fh.write(chunk)
                        written += len(chunk)

                if expected is not None and written != expected:
                    tmp_path.unlink(missing_ok=True)
                    raise ValueError(
                        f"Content-length mismatch downloading {url}: "
                        f"expected {expected}, got {written}"
                    )

                os.replace(tmp_path, dest_path)
                return

            except (requests.ConnectionError, requests.Timeout) as exc:
                last_exc = exc
            except requests.HTTPError as exc:
                status = exc.response.status_code if exc.response is not None else None
                if status is not None and status < 500:
                    raise
                last_exc = exc

            tmp_path.unlink(missing_ok=True)
            if attempt < self.max_retries and self.backoff_base:
                time.sleep(self.backoff_base * (2 ** attempt))

        assert last_exc is not None
        raise last_exc
```

Check whether `import os` is already at the top of `http_client.py`; if not, add it alongside the existing imports.

- [ ] **Step 4: Run to verify tests pass**

```
cd etl && .venv/bin/python -m pytest tests/test_tse_downloader.py -v
```

Expected: 8 PASSes

- [ ] **Step 5: Run full test suite (no regressions)**

```
cd etl && .venv/bin/python -m pytest -q
```

Expected: all existing tests still pass

- [ ] **Step 6: Commit**

```bash
git add etl/common/http_client.py etl/tests/test_tse_downloader.py
git commit -m "feat(etl): add TseDownloader for streaming large binary downloads"
```

---

### Task 3: TSE ZIP utilities (`common/tse_zip.py`)

**Files:**
- Create: `etl/common/tse_zip.py`
- Create: `etl/tests/test_tse_zip.py`

- [ ] **Step 1: Write the failing tests**

Create `etl/tests/test_tse_zip.py`:

```python
"""Tests for common.tse_zip — ZIP reading and manifest building."""
import csv
import io
import json
import zipfile
from pathlib import Path

import pytest

from common.tse_zip import ENCODING, FEDERAL_CARGOS, SOURCE, build_manifest


# ── helpers ──────────────────────────────────────────────────────────────────

COLUMNS = [
    "DS_ELEICAO", "DS_CARGO", "NM_CANDIDATO", "SG_PARTIDO",
    "NM_DOADOR", "NR_CPF_CNPJ_DOADOR", "VR_RECEITA", "DS_ORIGEM_RECEITA",
]

SAMPLE_ROWS = [
    # federal candidates
    ["ELEIÇÕES GERAIS 2022", "DEPUTADO FEDERAL", "JOAO SILVA", "PT",
     "MARIA SOUZA", "000.000.000-00", "1000.00", "Recursos de pessoas físicas"],
    ["ELEIÇÕES GERAIS 2022", "SENADOR", "ANA LIMA", "MDB",
     "CARLOS RAMOS", "111.111.111-11", "5000.00", "Recursos de pessoas físicas"],
    ["ELEIÇÕES GERAIS 2022", "PRESIDENTE", "JOSE BRASIL", "PL",
     "EMPRESA SA", "00.000.000/0001-00", "50000.00", "Recursos de partidos"],
    # non-federal — should NOT be counted in federal_rows
    ["ELEIÇÕES GERAIS 2022", "GOVERNADOR", "PEDRO ESTADUAL", "PP",
     "ANA SILVA", "222.222.222-22", "2000.00", "Recursos de pessoas físicas"],
]


def _make_zip(rows=SAMPLE_ROWS, filename="receitas_2022_BRASIL.csv", encoding=ENCODING):
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", compression=zipfile.ZIP_STORED) as zf:
        csv_buf = io.StringIO()
        writer = csv.writer(csv_buf, delimiter=";")
        writer.writerow(COLUMNS)
        writer.writerows(rows)
        zf.writestr(filename, csv_buf.getvalue().encode(encoding))
    buf.seek(0)
    return buf.read()


def _write_zip(tmp_path: Path, content: bytes, name: str = "test.zip") -> Path:
    p = tmp_path / name
    p.write_bytes(content)
    return p


# ── constants ────────────────────────────────────────────────────────────────

def test_federal_cargos_contains_expected_values():
    assert "DEPUTADO FEDERAL" in FEDERAL_CARGOS
    assert "SENADOR" in FEDERAL_CARGOS
    assert "PRESIDENTE" in FEDERAL_CARGOS
    assert "GOVERNADOR" not in FEDERAL_CARGOS


def test_encoding_is_latin1():
    assert ENCODING == "latin-1"


def test_source_value():
    assert SOURCE == "tse-dados-abertos"


# ── build_manifest ───────────────────────────────────────────────────────────

def test_manifest_meta_fields(tmp_path):
    p = _write_zip(tmp_path, _make_zip())
    result = build_manifest(p, "http://example.com/2022.zip")
    assert result["_meta"]["source"] == "tse-dados-abertos"
    assert result["_meta"]["source_url"] == "http://example.com/2022.zip"
    assert result["_meta"]["encoding"] == "latin-1"
    assert "fetched_at" in result["_meta"]


def test_manifest_lists_csv_files(tmp_path):
    p = _write_zip(tmp_path, _make_zip(filename="receitas_2022_BRASIL.csv"))
    result = build_manifest(p, "http://example.com/2022.zip")
    assert len(result["files"]) == 1
    assert result["files"][0]["filename"] == "receitas_2022_BRASIL.csv"


def test_manifest_extracts_column_names(tmp_path):
    p = _write_zip(tmp_path, _make_zip())
    result = build_manifest(p, "http://example.com/2022.zip")
    assert result["files"][0]["columns"] == COLUMNS


def test_manifest_counts_total_rows(tmp_path):
    p = _write_zip(tmp_path, _make_zip())
    result = build_manifest(p, "http://example.com/2022.zip")
    assert result["files"][0]["total_rows"] == 4


def test_manifest_counts_only_federal_rows(tmp_path):
    # 3 federal (DEPUTADO FEDERAL, SENADOR, PRESIDENTE) + 1 non-federal (GOVERNADOR)
    p = _write_zip(tmp_path, _make_zip())
    result = build_manifest(p, "http://example.com/2022.zip")
    assert result["files"][0]["federal_rows"] == 3


def test_manifest_handles_multi_file_zip(tmp_path):
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as zf:
        for state in ("SP", "RJ"):
            csv_buf = io.StringIO()
            writer = csv.writer(csv_buf, delimiter=";")
            writer.writerow(COLUMNS)
            # 1 federal row per state
            writer.writerow(
                ["ELEIÇÕES GERAIS 2022", "DEPUTADO FEDERAL", f"CAND {state}", "PT",
                 "DOADOR", "000", "100.00", "Recursos de pessoas físicas"]
            )
            zf.writestr(f"receitas_2022_{state}.csv", csv_buf.getvalue().encode(ENCODING))
    buf.seek(0)
    p = tmp_path / "multi.zip"
    p.write_bytes(buf.read())

    result = build_manifest(p, "http://example.com/multi.zip")
    assert len(result["files"]) == 2
    filenames = {f["filename"] for f in result["files"]}
    assert filenames == {"receitas_2022_SP.csv", "receitas_2022_RJ.csv"}
    for f in result["files"]:
        assert f["total_rows"] == 1
        assert f["federal_rows"] == 1


def test_manifest_raises_if_no_csv_in_zip(tmp_path):
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as zf:
        zf.writestr("README.txt", "nothing here")
    buf.seek(0)
    p = tmp_path / "empty.zip"
    p.write_bytes(buf.read())
    with pytest.raises(ValueError, match="No CSV files found"):
        build_manifest(p, "http://example.com/empty.zip")


def test_manifest_raises_if_ds_cargo_column_missing(tmp_path):
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as zf:
        csv_buf = io.StringIO()
        writer = csv.writer(csv_buf, delimiter=";")
        writer.writerow(["COL_A", "COL_B"])  # no DS_CARGO
        writer.writerow(["val", "val"])
        zf.writestr("bad.csv", csv_buf.getvalue().encode(ENCODING))
    buf.seek(0)
    p = tmp_path / "bad.zip"
    p.write_bytes(buf.read())
    with pytest.raises(ValueError, match="DS_CARGO"):
        build_manifest(p, "http://example.com/bad.zip")


def test_manifest_strips_bom_from_first_column(tmp_path):
    """Some TSE files open with a UTF-8 BOM despite being latin-1."""
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as zf:
        csv_buf = io.StringIO()
        writer = csv.writer(csv_buf, delimiter=";")
        # prepend BOM to first column name
        cols_with_bom = ["﻿" + COLUMNS[0]] + COLUMNS[1:]
        writer.writerow(cols_with_bom)
        writer.writerows(SAMPLE_ROWS[:1])
        zf.writestr("bom.csv", csv_buf.getvalue().encode(ENCODING))
    buf.seek(0)
    p = tmp_path / "bom.zip"
    p.write_bytes(buf.read())
    result = build_manifest(p, "http://example.com/bom.zip")
    assert result["files"][0]["columns"][0] == COLUMNS[0]  # BOM stripped
```

- [ ] **Step 2: Run to verify tests fail**

```
cd etl && .venv/bin/python -m pytest tests/test_tse_zip.py -v
```

Expected: ImportError — `common.tse_zip` does not exist yet

- [ ] **Step 3: Create `etl/common/tse_zip.py`**

```python
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
                columns = [c.strip().lstrip("﻿") for c in columns]

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
```

- [ ] **Step 4: Run to verify tests pass**

```
cd etl && .venv/bin/python -m pytest tests/test_tse_zip.py -v
```

Expected: all 13 tests pass

- [ ] **Step 5: Run full test suite**

```
cd etl && .venv/bin/python -m pytest -q
```

Expected: all existing tests still pass

- [ ] **Step 6: Commit**

```bash
git add etl/common/tse_zip.py etl/tests/test_tse_zip.py
git commit -m "feat(etl): add tse_zip utility for reading TSE ZIP manifests"
```

---

### Task 4: Receitas extract (`extract/tse/receitas.py`)

**Files:**
- Create: `etl/extract/tse/receitas.py`
- Create: `etl/tests/test_tse_receitas_extract.py`

> **Before implementing the URL constants:** Look up the correct download URLs for
> `receitas_candidatos` on the TSE open-data portal. Visit:
> - 2022: https://dadosabertos.tse.jus.br/dataset/prestacao-de-contas-eleitorais-2022
> - 2018: https://dadosabertos.tse.jus.br/dataset/prestacao-de-contas-eleitorais-2018
>
> Find the direct ZIP download links for the national (`BRASIL`) receitas file.
> Update `RECEITAS_URLS` with the verified URLs before running the script for real.

- [ ] **Step 1: Write the failing tests**

Create `etl/tests/test_tse_receitas_extract.py`:

```python
"""Tests for extract.tse.receitas — receitas_candidatos download and manifest."""
import csv
import io
import json
import zipfile
from pathlib import Path

import pytest

from common import paths
from extract.tse.receitas import ELECTIONS, run


# ── helpers ──────────────────────────────────────────────────────────────────

COLUMNS = [
    "DS_ELEICAO", "DS_CARGO", "NM_CANDIDATO", "SG_PARTIDO",
    "NM_DOADOR", "NR_CPF_CNPJ_DOADOR", "VR_RECEITA", "DS_ORIGEM_RECEITA",
]

ROWS = [
    ["ELEIÇÕES GERAIS 2022", "DEPUTADO FEDERAL", "CAND A", "PT",
     "DOADOR A", "000", "500.00", "Recursos de pessoas físicas"],
    ["ELEIÇÕES GERAIS 2022", "GOVERNADOR", "CAND B", "MDB",
     "DOADOR B", "111", "200.00", "Recursos de pessoas físicas"],
]


def _make_zip(rows=ROWS, filename="receitas_2022_BRASIL.csv"):
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", compression=zipfile.ZIP_STORED) as zf:
        csv_buf = io.StringIO()
        writer = csv.writer(csv_buf, delimiter=";")
        writer.writerow(COLUMNS)
        writer.writerows(rows)
        zf.writestr(filename, csv_buf.getvalue().encode("latin-1"))
    buf.seek(0)
    return buf.read()


class FakeDownloader:
    """Writes a pre-built ZIP to dest_path without making any HTTP request."""

    def __init__(self, zip_content: bytes):
        self._zip_content = zip_content

    def download(self, url: str, dest_path: Path) -> None:
        dest_path.parent.mkdir(parents=True, exist_ok=True)
        dest_path.write_bytes(self._zip_content)


# ── tests ────────────────────────────────────────────────────────────────────

def test_run_writes_zip_file(tmp_path):
    content = _make_zip()
    run(downloader=FakeDownloader(content), elections=(2022,), out_dir=tmp_path)
    assert paths.tse_receitas_zip_path(2022, base=tmp_path).read_bytes() == content


def test_run_writes_manifest_file(tmp_path):
    run(downloader=FakeDownloader(_make_zip()), elections=(2022,), out_dir=tmp_path)
    manifest_path = paths.tse_receitas_manifest_path(2022, base=tmp_path)
    assert manifest_path.exists()


def test_run_manifest_contains_correct_source(tmp_path):
    run(downloader=FakeDownloader(_make_zip()), elections=(2022,), out_dir=tmp_path)
    manifest = json.loads(
        paths.tse_receitas_manifest_path(2022, base=tmp_path).read_text()
    )
    assert manifest["_meta"]["source"] == "tse-dados-abertos"


def test_run_manifest_federal_rows_correct(tmp_path):
    # ROWS has 1 federal (DEPUTADO FEDERAL) and 1 non-federal (GOVERNADOR)
    run(downloader=FakeDownloader(_make_zip()), elections=(2022,), out_dir=tmp_path)
    manifest = json.loads(
        paths.tse_receitas_manifest_path(2022, base=tmp_path).read_text()
    )
    assert manifest["files"][0]["total_rows"] == 2
    assert manifest["files"][0]["federal_rows"] == 1


def test_run_processes_multiple_years(tmp_path):
    run(
        downloader=FakeDownloader(_make_zip()),
        elections=(2018, 2022),
        out_dir=tmp_path,
    )
    assert paths.tse_receitas_zip_path(2018, base=tmp_path).exists()
    assert paths.tse_receitas_zip_path(2022, base=tmp_path).exists()
    assert paths.tse_receitas_manifest_path(2018, base=tmp_path).exists()
    assert paths.tse_receitas_manifest_path(2022, base=tmp_path).exists()


def test_run_returns_written_paths(tmp_path):
    result = run(
        downloader=FakeDownloader(_make_zip()),
        elections=(2022,),
        out_dir=tmp_path,
    )
    assert result == [paths.tse_receitas_zip_path(2022, base=tmp_path)]


def test_elections_constant():
    assert ELECTIONS == (2018, 2022)
```

- [ ] **Step 2: Run to verify tests fail**

```
cd etl && .venv/bin/python -m pytest tests/test_tse_receitas_extract.py -v
```

Expected: ImportError — `extract.tse.receitas` does not exist

- [ ] **Step 3: Create `etl/extract/tse/receitas.py`**

First, look up the correct URLs by visiting the TSE portal pages listed above. Then create the file:

```python
"""Extract step: download TSE receitas_candidatos bulk ZIPs for 2018 and 2022.

Downloads campaign donation CSVs from the TSE open-data portal and saves them
verbatim to data/raw/tse/receitas/.  A manifest JSON is written alongside each
ZIP, recording column names and row counts — resolving the open verification
item in decisions.md about TSE column names.

IMPORTANT: Verify RECEITAS_URLS against https://dadosabertos.tse.jus.br before
running.  The portal pages to check are:
  2022: https://dadosabertos.tse.jus.br/dataset/prestacao-de-contas-eleitorais-2022
  2018: https://dadosabertos.tse.jus.br/dataset/prestacao-de-contas-eleitorais-2018

Run with:
    python -m extract.tse.receitas
"""
from __future__ import annotations

from pathlib import Path
from typing import Dict, List, Optional, Sequence

from common import paths
from common.http_client import TseDownloader
from common.jsonio import write_json_atomic
from common.tse_zip import build_manifest

ELECTIONS = (2018, 2022)

# VERIFY these URLs against the TSE open-data portal before running.
RECEITAS_URLS: Dict[int, str] = {
    2018: "https://cdn.tse.jus.br/estatistica/sead/odsele/prestacao_contas/prestacao_contas_final_2018.zip",
    2022: "https://cdn.tse.jus.br/estatistica/sead/odsele/prestacao_contas/prestacao_contas_final_2022.zip",
}


def run(
    downloader: Optional[TseDownloader] = None,
    elections: Sequence[int] = ELECTIONS,
    out_dir: Optional[Path] = None,
) -> List[Path]:
    """Download each election year's receitas ZIP and write a manifest alongside it.

    Returns the list of written ZIP paths.
    """
    downloader = downloader or TseDownloader()
    written: List[Path] = []

    for year in elections:
        url = RECEITAS_URLS[year]
        zip_path = paths.tse_receitas_zip_path(year, base=out_dir)
        manifest_path = paths.tse_receitas_manifest_path(year, base=out_dir)

        print(f"receitas {year}: downloading from {url} ...")
        downloader.download(url, zip_path)
        print(f"  saved {zip_path} ({zip_path.stat().st_size:,} bytes)")

        manifest = build_manifest(zip_path, url)
        write_json_atomic(manifest, manifest_path)

        for f in manifest["files"]:
            print(
                f"  {f['filename']}: {f['total_rows']:,} rows, "
                f"{f['federal_rows']:,} federal"
            )

        written.append(zip_path)

    return written


if __name__ == "__main__":
    run()
```

- [ ] **Step 4: Run to verify tests pass**

```
cd etl && .venv/bin/python -m pytest tests/test_tse_receitas_extract.py -v
```

Expected: 7 PASSes

- [ ] **Step 5: Run full test suite**

```
cd etl && .venv/bin/python -m pytest -q
```

Expected: all existing tests still pass

- [ ] **Step 6: Commit**

```bash
git add etl/extract/tse/receitas.py etl/tests/test_tse_receitas_extract.py
git commit -m "feat(etl): add TSE receitas_candidatos extract script"
```

---

### Task 5: Candidatos extract (`extract/tse/candidatos.py`)

**Files:**
- Create: `etl/extract/tse/candidatos.py`
- Create: `etl/tests/test_tse_candidatos_extract.py`

> **Before implementing the URL constants:** Look up the correct download URLs for
> `consulta_cand` on the TSE open-data portal. Visit:
> - 2022: https://dadosabertos.tse.jus.br/dataset/candidatos-2022
> - 2018: https://dadosabertos.tse.jus.br/dataset/candidatos-2018
>
> Find the direct ZIP download links for the national (`BRASIL`) consulta_cand file.
> Confirm the column name for the candidate's CPF (expected: `NR_CPF_CANDIDATO`).

- [ ] **Step 1: Write the failing tests**

Create `etl/tests/test_tse_candidatos_extract.py`:

```python
"""Tests for extract.tse.candidatos — consulta_cand download and manifest."""
import csv
import io
import json
import zipfile
from pathlib import Path

from common import paths
from extract.tse.candidatos import ELECTIONS, run


# ── helpers ──────────────────────────────────────────────────────────────────

COLUMNS = [
    "DS_ELEICAO", "DS_CARGO", "NM_CANDIDATO", "SG_PARTIDO",
    "NR_CPF_CANDIDATO", "SG_UF", "NR_CANDIDATO",
]

ROWS = [
    ["ELEIÇÕES GERAIS 2022", "DEPUTADO FEDERAL", "CAND A", "PT",
     "000.000.000-00", "SP", "1234"],
    ["ELEIÇÕES GERAIS 2022", "GOVERNADOR", "CAND B", "MDB",
     "111.111.111-11", "RJ", "5678"],
]


def _make_zip(rows=ROWS, filename="consulta_cand_2022_BRASIL.csv"):
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", compression=zipfile.ZIP_STORED) as zf:
        csv_buf = io.StringIO()
        writer = csv.writer(csv_buf, delimiter=";")
        writer.writerow(COLUMNS)
        writer.writerows(rows)
        zf.writestr(filename, csv_buf.getvalue().encode("latin-1"))
    buf.seek(0)
    return buf.read()


class FakeDownloader:
    def __init__(self, zip_content: bytes):
        self._zip_content = zip_content

    def download(self, url: str, dest_path: Path) -> None:
        dest_path.parent.mkdir(parents=True, exist_ok=True)
        dest_path.write_bytes(self._zip_content)


# ── tests ────────────────────────────────────────────────────────────────────

def test_run_writes_zip_file(tmp_path):
    content = _make_zip()
    run(downloader=FakeDownloader(content), elections=(2022,), out_dir=tmp_path)
    assert paths.tse_candidatos_zip_path(2022, base=tmp_path).read_bytes() == content


def test_run_writes_manifest_file(tmp_path):
    run(downloader=FakeDownloader(_make_zip()), elections=(2022,), out_dir=tmp_path)
    assert paths.tse_candidatos_manifest_path(2022, base=tmp_path).exists()


def test_run_manifest_federal_rows_correct(tmp_path):
    # ROWS has 1 federal (DEPUTADO FEDERAL) and 1 non-federal (GOVERNADOR)
    run(downloader=FakeDownloader(_make_zip()), elections=(2022,), out_dir=tmp_path)
    manifest = json.loads(
        paths.tse_candidatos_manifest_path(2022, base=tmp_path).read_text()
    )
    assert manifest["files"][0]["total_rows"] == 2
    assert manifest["files"][0]["federal_rows"] == 1


def test_run_processes_multiple_years(tmp_path):
    run(
        downloader=FakeDownloader(_make_zip()),
        elections=(2018, 2022),
        out_dir=tmp_path,
    )
    assert paths.tse_candidatos_zip_path(2018, base=tmp_path).exists()
    assert paths.tse_candidatos_zip_path(2022, base=tmp_path).exists()
    assert paths.tse_candidatos_manifest_path(2018, base=tmp_path).exists()
    assert paths.tse_candidatos_manifest_path(2022, base=tmp_path).exists()


def test_run_returns_written_paths(tmp_path):
    result = run(
        downloader=FakeDownloader(_make_zip()),
        elections=(2022,),
        out_dir=tmp_path,
    )
    assert result == [paths.tse_candidatos_zip_path(2022, base=tmp_path)]


def test_elections_constant():
    assert ELECTIONS == (2018, 2022)
```

- [ ] **Step 2: Run to verify tests fail**

```
cd etl && .venv/bin/python -m pytest tests/test_tse_candidatos_extract.py -v
```

Expected: ImportError — `extract.tse.candidatos` does not exist

- [ ] **Step 3: Create `etl/extract/tse/candidatos.py`**

Look up the verified URLs (see note above), then create:

```python
"""Extract step: download TSE consulta_cand bulk ZIPs for 2018 and 2022.

Downloads the TSE candidate registry (including NR_CPF_CANDIDATO) from the TSE
open-data portal and saves verbatim to data/raw/tse/candidatos/.  A manifest
JSON is written alongside each ZIP.

These CPFs are used in the transform step to link TSE candidates to the
deputy/senator entities in pegada.db (requires the bio-detail extract to have
run first to populate CPFs on the Câmara/Senado side).

IMPORTANT: Verify CANDIDATOS_URLS against https://dadosabertos.tse.jus.br before
running.  The portal pages to check are:
  2022: https://dadosabertos.tse.jus.br/dataset/candidatos-2022
  2018: https://dadosabertos.tse.jus.br/dataset/candidatos-2018

Run with:
    python -m extract.tse.candidatos
"""
from __future__ import annotations

from pathlib import Path
from typing import Dict, List, Optional, Sequence

from common import paths
from common.http_client import TseDownloader
from common.jsonio import write_json_atomic
from common.tse_zip import build_manifest

ELECTIONS = (2018, 2022)

# VERIFY these URLs against the TSE open-data portal before running.
CANDIDATOS_URLS: Dict[int, str] = {
    2018: "https://cdn.tse.jus.br/estatistica/sead/odsele/consulta_cand/consulta_cand_2018.zip",
    2022: "https://cdn.tse.jus.br/estatistica/sead/odsele/consulta_cand/consulta_cand_2022.zip",
}


def run(
    downloader: Optional[TseDownloader] = None,
    elections: Sequence[int] = ELECTIONS,
    out_dir: Optional[Path] = None,
) -> List[Path]:
    """Download each election year's consulta_cand ZIP and write a manifest.

    Returns the list of written ZIP paths.
    """
    downloader = downloader or TseDownloader()
    written: List[Path] = []

    for year in elections:
        url = CANDIDATOS_URLS[year]
        zip_path = paths.tse_candidatos_zip_path(year, base=out_dir)
        manifest_path = paths.tse_candidatos_manifest_path(year, base=out_dir)

        print(f"candidatos {year}: downloading from {url} ...")
        downloader.download(url, zip_path)
        print(f"  saved {zip_path} ({zip_path.stat().st_size:,} bytes)")

        manifest = build_manifest(zip_path, url)
        write_json_atomic(manifest, manifest_path)

        for f in manifest["files"]:
            print(
                f"  {f['filename']}: {f['total_rows']:,} rows, "
                f"{f['federal_rows']:,} federal"
            )

        written.append(zip_path)

    return written


if __name__ == "__main__":
    run()
```

- [ ] **Step 4: Run to verify tests pass**

```
cd etl && .venv/bin/python -m pytest tests/test_tse_candidatos_extract.py -v
```

Expected: 6 PASSes

- [ ] **Step 5: Run full test suite**

```
cd etl && .venv/bin/python -m pytest -q
```

Expected: all tests pass (new + existing)

- [ ] **Step 6: Commit**

```bash
git add etl/extract/tse/candidatos.py etl/tests/test_tse_candidatos_extract.py
git commit -m "feat(etl): add TSE consulta_cand extract script"
```

---

## Post-Implementation Verification

After all tasks are committed, run the full extract for real data:

```bash
cd etl && .venv/bin/python -m extract.tse.receitas
cd etl && .venv/bin/python -m extract.tse.candidatos
```

Check the manifests to confirm:
1. Column names match what the spec assumed (especially `DS_CARGO`, `NR_CPF_CNPJ_DOADOR`, `NR_CPF_CANDIDATO`)
2. `DS_CARGO` values for federal candidates match `FEDERAL_CARGOS` exactly (check a few rows with `federal_rows > 0`)
3. If column names differ from what was assumed, update `FEDERAL_CARGOS` in `common/tse_zip.py` and note the correction in `decisions.md`

Mark the open verification item in `decisions.md` as resolved:
> "TSE donations column names — inferred from regulation/docs (e.g. NR_CPF_CNPJ_DOADOR), not yet verified against an actual file header / LEIA-ME"
